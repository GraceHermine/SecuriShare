import uuid
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator
from django.contrib.auth.models import AbstractUser, BaseUserManager, Group, Permission
 
 
# =============================================================
# USER MANAGER
# =============================================================
class UserManager(BaseUserManager):
 
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("L'email doit être défini")
        email = self.normalize_email(email)
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('is_active', True)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
 
    def create_superuser(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("L'email doit être défini")
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        if extra_fields.get('is_staff') is not True:
            raise ValueError("Le superuser doit avoir is_staff=True.")
        if extra_fields.get('is_superuser') is not True:
            raise ValueError("Le superuser doit avoir is_superuser=True.")
        return self.create_user(email, password, **extra_fields)
 
 
# =============================================================
# USER MODEL
# =============================================================
class User(AbstractUser):
    """
    Modèle utilisateur custom pour DocuSafe.
    Authentification par email (pas de username).
    """
 
    username = None  # Supprimé au profit de l'email
 
    # Résolution des conflits de related_name avec Django
    groups = models.ManyToManyField(
        Group,
        related_name="docusafe_users",
        blank=True,
        verbose_name=_("groupes"),
    )
    user_permissions = models.ManyToManyField(
        Permission,
        related_name="docusafe_user_permissions",
        blank=True,
        verbose_name=_("permissions"),
    )
 
    class Gender(models.TextChoices):
        MALE   = "H", _("Homme")
        FEMALE = "F", _("Femme")
        OTHER  = "A", _("Autre")
 
    class Role(models.TextChoices):
        USER  = "user",  _("Utilisateur")
        ADMIN = "admin", _("Administrateur")
 
    # ── Identité ──────────────────────────────────────────────
    email   = models.EmailField(unique=True, verbose_name=_("Email"))
    nom     = models.CharField(max_length=255, verbose_name=_("Nom"))
    prenom  = models.CharField(max_length=255, verbose_name=_("Prénom"))
    genre   = models.CharField(
        max_length=1, choices=Gender.choices,
        null=True, blank=True, verbose_name=_("Genre")
    )
    datenaiss = models.DateField(null=True, blank=True, verbose_name=_("Date de naissance"))
 
    # ── Contact ───────────────────────────────────────────────
    numero = models.CharField(
        max_length=15, unique=True, null=True, blank=True,
        verbose_name=_("Numéro de téléphone"),
        validators=[
            RegexValidator(
                regex=r"^225\d{10}$",
                message=_("Le numéro doit être au format 225XXXXXXXXXX (ex: 2250102030405)")
            )
        ]
    )
    adresse = models.TextField(null=True, blank=True, verbose_name=_("Adresse"))
 
    # ── Photo de profil ───────────────────────────────────────
    photo = models.ImageField(
        upload_to='users/photos/',
        null=True, blank=True,
        verbose_name=_("Photo de profil")
    )
 
    # ── Rôle & statut ─────────────────────────────────────────
    role   = models.CharField(
        max_length=10, choices=Role.choices,
        default=Role.USER, verbose_name=_("Rôle")
    )
    statut = models.BooleanField(default=True, verbose_name=_("Compte actif"))
 
    # ── MFA ───────────────────────────────────────────────────
    mfa_enabled = models.BooleanField(default=False, verbose_name=_("MFA activé"))
    mfa_secret  = models.CharField(
        max_length=64, null=True, blank=True,
        verbose_name=_("Secret MFA (TOTP)")
    )
 
    # ── Timestamps ────────────────────────────────────────────
    created_at      = models.DateTimeField(auto_now_add=True, verbose_name=_("Créé le"))
    last_updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Mis à jour le"))
 
    # ── Manager & AUTH config ─────────────────────────────────
    objects = UserManager()
 
    USERNAME_FIELD  = 'email'
    EMAIL_FIELD     = 'email'
    REQUIRED_FIELDS = ['nom', 'prenom']
 
    class Meta:
        verbose_name = _("Utilisateur")
        verbose_name_plural = _("Utilisateurs")
        ordering = ['-created_at']
 
    def __str__(self):
        return f"{self.prenom} {self.nom} <{self.email}>"
 
    @property
    def full_name(self):
        return f"{self.prenom} {self.nom}".strip()
 
    @property
    def is_admin_user(self):
        return self.role == self.Role.ADMIN or self.is_staff
 
 
# =============================================================
# PASSWORD RESET
# =============================================================
class PasswordResetCode(models.Model):
    """
    Code OTP à 6 chiffres envoyé par email pour réinitialiser le mot de passe.
    Valide 5 minutes.
    """
    user       = models.ForeignKey(
        User, on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="reset_codes",
        verbose_name=_("Utilisateur")
    )
    email      = models.EmailField(verbose_name=_("Email"))
    code       = models.CharField(max_length=6, verbose_name=_("Code OTP"))
    token      = models.UUIDField(
        default=uuid.uuid4, editable=False, unique=True,
        verbose_name=_("Token de validation")
    )
    used       = models.BooleanField(default=False, verbose_name=_("Utilisé"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Créé le"))
 
    class Meta:
        verbose_name = _("Code de réinitialisation")
        verbose_name_plural = _("Codes de réinitialisation")
        ordering = ['-created_at']
 
    def is_valid(self):
        """Valide pendant 5 minutes et non encore utilisé."""
        not_expired = (timezone.now() - self.created_at).total_seconds() <= 300
        return not_expired and not self.used
 
    def mark_used(self):
        self.used = True
        self.save(update_fields=['used'])
 
    def __str__(self):
        return f"{self.email} — code {self.code} ({'valide' if self.is_valid() else 'expiré'})"
 
 
# =============================================================
# SESSION / CONNEXION
# =============================================================
class LoginAttempt(models.Model):
    """
    Trace les tentatives de connexion (réussies et échouées).
    Utile pour la détection d'intrusion et les rapports de sécurité.
    """
    user       = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="login_attempts",
        verbose_name=_("Utilisateur")
    )
    email      = models.EmailField(verbose_name=_("Email tenté"))
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name=_("Adresse IP"))
    user_agent = models.TextField(null=True, blank=True, verbose_name=_("User-Agent"))
    success    = models.BooleanField(default=False, verbose_name=_("Réussie"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Date"))
 
    class Meta:
        verbose_name = _("Tentative de connexion")
        verbose_name_plural = _("Tentatives de connexion")
        ordering = ['-created_at']
 
    def __str__(self):
        status = "✓" if self.success else "✗"
        return f"[{status}] {self.email} — {self.ip_address} — {self.created_at:%d/%m/%Y %H:%M}"
 