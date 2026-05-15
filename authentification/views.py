from django.shortcuts import render

# Create your views here.
import random
import string
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from datetime import timedelta

from user.models import ActivityLog

from .models import User, LoginAttempt, PasswordResetCode   


# ════════════════════════════════════════════════════════
# HELPERS INTERNES
# ════════════════════════════════════════════════════════

def get_client_ip(request):
    """Récupère l'IP réelle du client (compatible reverse proxy)."""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


def is_brute_force(email, ip):
    """
    Bloque si :
      - 5+ échecs sur le même email en 15 min, OU
      - 10+ échecs depuis la même IP en 15 min.
    """
    since = timezone.now() - timedelta(minutes=15)
    by_email = LoginAttempt.objects.filter(
        email=email, success=False, created_at__gte=since
    ).count()
    by_ip = LoginAttempt.objects.filter(
        ip_address=ip, success=False, created_at__gte=since
    ).count()
    return by_email >= 5 or by_ip >= 10


def remaining_attempts(email):
    """Retourne le nombre de tentatives restantes avant blocage (max 5)."""
    since = timezone.now() - timedelta(minutes=15)
    failed = LoginAttempt.objects.filter(
        email=email, success=False, created_at__gte=since
    ).count()
    return max(0, 5 - failed)


def log_attempt(request, email, success, user=None):
    """Enregistre une tentative de connexion dans LoginAttempt."""
    LoginAttempt.objects.create(
        user=user,
        email=email,
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
        success=success,
    )


def log_activity(user, action, request=None, description='', document=None):
    """Crée une entrée dans le journal ActivityLog."""
    ActivityLog.objects.create(
        user=user,
        action=action,
        description=description,
        document=document,
        ip_address=get_client_ip(request) if request else None,
    )


def generate_otp(length=6):
    """Génère un code OTP numérique aléatoire."""
    return ''.join(random.choices(string.digits, k=length))


# ════════════════════════════════════════════════════════
# VUE 1 — CONNEXION
# ════════════════════════════════════════════════════════

@never_cache
@require_http_methods(["GET", "POST"])
def login_view(request):
    """
    Connexion par email + mot de passe.

    Sécurités :
      - USERNAME_FIELD = 'email' → authenticate(username=email)
      - Protection brute-force : 5 échecs = blocage 15 min
      - Compte désactivé (statut=False) = refus
      - Traçage complet via LoginAttempt + ActivityLog
      - "Se souvenir" : session 30 jours vs fermeture navigateur
      - Redirection propre vers ?next=
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    context = {}

    if request.method == 'POST':
        email    = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        remember = request.POST.get('remember', False)
        ip       = get_client_ip(request)

        context['email'] = email

        # ── Validation des champs ──────────────────────────────
        if not email or not password:
            messages.error(request, 'Veuillez renseigner votre email et votre mot de passe.')
            return render(request, 'home.html', context)

        # ── Protection brute-force ─────────────────────────────
        if is_brute_force(email, ip):
            log_attempt(request, email, success=False)
            messages.error(
                request,
                'Accès temporairement bloqué suite à trop de tentatives échouées. '
                'Réessayez dans 15 minutes.'
            )
            context['blocked'] = True
            return render(request, 'home.html', context)

        # ── Authentification ────────────────────────────────────
        user = authenticate(request, username=email, password=password)

        if user is not None:

            # Compte désactivé
            if not user.statut:
                log_attempt(request, email, success=False, user=user)
                messages.error(
                    request,
                    'Votre compte est désactivé. Contactez votre administrateur.'
                )
                return render(request, 'login.html', context)

            # ✅ Connexion réussie
            login(request, user)

            request.session.set_expiry(
                60 * 60 * 24 * 30 if remember else 0
            )

            log_attempt(request, email, success=True, user=user)
            log_activity(
                user, ActivityLog.Action.LOGIN, request,
                description=f'Connexion depuis {ip}'
            )

            messages.success(request, f'Bienvenue, {user.full_name} !')
            next_url = request.GET.get('next') or 'dashboard'
            return redirect(next_url)

        else:
            # ❌ Échec — on cherche l'user pour lier le log
            try:
                failed_user = User.objects.get(email=email)
            except User.DoesNotExist:
                failed_user = None

            log_attempt(request, email, success=False, user=failed_user)

            left = remaining_attempts(email)
            if left > 0:
                messages.error(
                    request,
                    f'Email ou mot de passe incorrect. '
                    f'Il vous reste {left} tentative(s) avant blocage temporaire.'
                )
            else:
                messages.error(
                    request,
                    'Trop de tentatives échouées. Accès bloqué pendant 15 minutes.'
                )

    return render(request, 'login.html', context)


# ════════════════════════════════════════════════════════
# VUE 2 — DÉCONNEXION
# ════════════════════════════════════════════════════════

@require_http_methods(["GET", "POST"])
def logout_view(request):
    """
    Déconnexion sécurisée.
    - Log d'activité avant la déconnexion (user encore accessible)
    - Accepte GET et POST (bouton de formulaire ou lien)
    """
    if request.user.is_authenticated:
        log_activity(
            request.user, ActivityLog.Action.LOGOUT, request,
            description='Déconnexion manuelle'
        )
        logout(request)
    messages.success(request, 'Vous avez été déconnecté avec succès.')
    return redirect('login')


# ════════════════════════════════════════════════════════
# VUE 3 — MOT DE PASSE OUBLIÉ (étape 1 : email)
# ════════════════════════════════════════════════════════

@never_cache
@require_http_methods(["GET", "POST"])
def forgot_password_view(request):
    """
    Étape 1 : l'utilisateur saisit son email.

    Sécurité :
      - Message neutre que l'email existe ou non (évite l'énumération)
      - Invalide les anciens codes non utilisés avant d'en créer un nouveau
      - OTP affiché en console en DEV (à remplacer par send_mail() en prod)
    """
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()

        if not email:
            messages.error(request, 'Veuillez saisir votre adresse email.')
            return render(request, 'forgot_password.html')

        try:
            user = User.objects.get(email=email)

            # Invalider les codes précédents
            PasswordResetCode.objects.filter(user=user, used=False).update(used=True)

            # Créer le nouveau code OTP
            code = generate_otp()
            reset = PasswordResetCode.objects.create(
                user=user,
                email=email,
                code=code,
            )

            # ── En production : send_mail() ──────────────────
            # from django.core.mail import send_mail
            # send_mail(
            #     subject='DocuSafe – Code de vérification',
            #     message=f'Votre code : {code} (valide 5 minutes)',
            #     from_email='no-reply@docusafe.com',
            #     recipient_list=[email],
            # )

            # ── En développement : console ───────────────────
            print(f'\n{"─"*50}')
            print(f'[DEV] OTP pour {email}')
            print(f'  Code  : {code}')
            print(f'  Token : {reset.token}')
            print(f'{"─"*50}\n')

        except User.DoesNotExist:
            pass  # message neutre intentionnel

        messages.success(
            request,
            f'Si un compte DocuSafe existe pour {email}, '
            f'un code de vérification vient d\'être envoyé.'
        )
        return redirect(f"{'/verifier-otp/'}?email={email}")

    return render(request, 'forgot_password.html')


# ════════════════════════════════════════════════════════
# VUE 4 — VÉRIFICATION OTP (étape 2)
# ════════════════════════════════════════════════════════

@never_cache
@require_http_methods(["GET", "POST"])
def verify_otp_view(request):
    """
    Étape 2 : l'utilisateur saisit le code OTP reçu.

    - Valide le code (5 min, non utilisé)
    - Redirige vers la page de nouveau mot de passe avec le token UUID
    """
    email = request.GET.get('email', request.POST.get('email', '')).strip().lower()
    context = {'email': email}

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()

        if not code or not email:
            messages.error(request, 'Code ou email manquant.')
            return render(request, 'verify_otp.html', context)

        try:
            reset = PasswordResetCode.objects.filter(
                email=email, code=code, used=False
            ).latest('created_at')

            if not reset.is_valid():
                messages.error(
                    request,
                    'Ce code a expiré (5 minutes). '
                    'Veuillez faire une nouvelle demande.'
                )
                return render(request, 'verify_otp.html', context)

            # ✅ Code valide → redirection avec token sécurisé
            return redirect('reset_password', token=str(reset.token))

        except PasswordResetCode.DoesNotExist:
            messages.error(
                request,
                'Code incorrect. Vérifiez votre email ou demandez un nouveau code.'
            )

    return render(request, 'verify_otp.html', context)


# ════════════════════════════════════════════════════════
# VUE 5 — NOUVEAU MOT DE PASSE (étape 3)
# ════════════════════════════════════════════════════════

@never_cache
@require_http_methods(["GET", "POST"])
def reset_password_view(request, token):
    """
    Étape 3 : l'utilisateur définit son nouveau mot de passe.

    - Le token UUID est l'unique preuve que l'OTP a été validé
    - Validation : 2 champs concordants, min 8 caractères
    - Marque le code comme utilisé après succès
    - Log d'activité PASSWORD_RESET
    """
    reset = get_object_or_404(PasswordResetCode, token=token, used=False)

    if not reset.is_valid():
        messages.error(request, 'Ce lien de réinitialisation a expiré.')
        return redirect('forgot_password')

    context = {'token': token}

    if request.method == 'POST':
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')

        # ── Validations ────────────────────────────────────────
        errors = []
        if not password1 or not password2:
            errors.append('Veuillez renseigner les deux champs.')
        elif password1 != password2:
            errors.append('Les mots de passe ne correspondent pas.')
        elif len(password1) < 8:
            errors.append('Le mot de passe doit contenir au moins 8 caractères.')

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'reset_password.html', context)

        # ✅ Mise à jour du mot de passe
        user = reset.user
        user.set_password(password1)
        user.save(update_fields=['password'])

        reset.mark_used()

        log_activity(
            user, ActivityLog.Action.PASSWORD_RESET, request,
            description='Réinitialisation du mot de passe via OTP'
        )

        messages.success(
            request,
            'Mot de passe mis à jour avec succès. Vous pouvez maintenant vous connecter.'
        )
        return redirect('login')

    return render(request, 'reset_password.html', context)

