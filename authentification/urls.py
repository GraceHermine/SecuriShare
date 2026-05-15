from django.urls import path
from . import views


urlpatterns = [
    # ── Authentification ──────────────────────────────────
    path('',                          views.login_view,          name='login'),
    path('login/',                    views.login_view,          name='login'),
    path('logout/',                   views.logout_view,         name='logout'),

    # ── Réinitialisation mot de passe (3 étapes) ──────────
    path('mot-de-passe-oublie/',      views.forgot_password_view, name='forgot_password'),
    path('verifier-otp/',             views.verify_otp_view,      name='verify_otp'),
    path('nouveau-mdp/<uuid:token>/', views.reset_password_view,  name='reset_password'),

   
]