import time

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache


@never_cache
def portal_login_view(request):
    """
    Renders and processes the ProcureSphere 360 ERP Portal login form.
    If an authenticated user visits /login/, redirect them to their role dashboard
    to prevent terminating active sessions.
    """
    if request.user.is_authenticated:
        reason = request.GET.get("reason", "").strip().lower()
        if (
            reason in ["signed_out", "logged_out", "back_navigation", "logout", "another_tab", "inactivity"]
            or request.COOKIES.get("ps360_just_logged_out") == "1"
            or request.COOKIES.get("ps360_user_signed_out") == "1"
        ):
            logout(request)
            context = {}
            if reason == "another_tab":
                context["session_expired_notice"] = (
                    "Your account was signed into in another tab or window. This session has been closed for security."
                )
            elif reason in ["inactivity", "session_expired"]:
                context["session_expired_notice"] = (
                    "Your session timed out after 5 minutes of inactivity. Please sign in again."
                )
            else:
                context["session_expired_notice"] = (
                    "You have been signed out of your session."
                )
            response = render(request, "pages/login.html", context)
            response.delete_cookie("ps360_just_logged_out")
            response.delete_cookie("ps360_user_signed_out")
            return response

        from apps.core.views import get_dashboard_url_for_user

        next_url = request.GET.get("next")
        if next_url and not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            next_url = None
        if not next_url:
            next_url = get_dashboard_url_for_user(request.user)
        return redirect(next_url)

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":

        email = (request.POST.get("email") or request.POST.get("username") or "").strip().lower()

        password = request.POST.get("password", "")



        if not email or not password:
            if is_ajax:
                return JsonResponse({"ok": False, "error": "Please provide both email and password."}, status=400)
            messages.error(request, "Please provide both email and password.")

            return render(request, "pages/login.html", {"email": email})



        # Explicit request=request keyword parameter is required for django-axes compatibility
        from apps.accounts.models import User
        matched_user = User.objects.filter(email__iexact=str(email).strip()).first()
        auth_username = matched_user.email if matched_user else email

        user = authenticate(request=request, username=auth_username, password=password)



        if user is not None:

            if not user.is_active:
                if is_ajax:
                    return JsonResponse({"ok": False, "error": "Your account has been deactivated. Please contact support."}, status=403)
                messages.error(

                    request, "Your account has been deactivated. Please contact support."

                )

                return render(request, "pages/login.html", {"email": email})



            login(request, user)
            request.session["_last_activity_ts"] = time.time()



            # Record AuditLog for authentication

            try:

                from apps.audit.models import AuditLog
                from apps.audit.services import create_audit_log_service



                create_audit_log_service(

                    actor=user,

                    action=AuditLog.ACTION_LOGIN,

                    target_model="User",

                    target_object_id=str(user.id),

                    new_state={

                        "email": user.email,

                        "role": user.role_code if hasattr(user, "role_code") else None,

                    },

                    ip_address=request.META.get("REMOTE_ADDR"),

                    user_agent=request.META.get("HTTP_USER_AGENT", ""),

                )

            except (ImportError, Exception):

                pass



            if getattr(user, "must_change_password", False):
                try:
                    change_url = reverse("accounts:change_password")
                except Exception:
                    change_url = reverse("change_password")
                if is_ajax:
                    response = JsonResponse({"ok": True, "redirect": change_url})
                else:
                    response = redirect(change_url)
                response.delete_cookie("ps360_just_logged_out")
                response.delete_cookie("ps360_user_signed_out")
                return response

            next_url = request.GET.get("next") or request.POST.get("next")
            if next_url and not url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                next_url = None  # never redirect off-site (open-redirect protection)
            if not next_url:
                from apps.core.views import get_dashboard_url_for_user

                next_url = get_dashboard_url_for_user(user)

            if is_ajax:
                response = JsonResponse({"ok": True, "redirect": next_url})
            else:
                response = redirect(next_url)
            response.delete_cookie("ps360_just_logged_out")
            response.delete_cookie("ps360_user_signed_out")
            return response

        else:
            from apps.accounts.models import User

            inactive_user = User.objects.filter(email__iexact=email).first()

            try:
                from apps.audit.models import AuditLog
                from apps.audit.services import create_audit_log_service

                matched_user = User.objects.filter(email__iexact=str(email).strip()).first()
                create_audit_log_service(
                    actor=matched_user,
                    action=AuditLog.ACTION_LOGIN_FAILED,
                    target_model="User",
                    target_object_id=str(matched_user.id if matched_user else email),
                    new_state={
                        "event": "LOGIN_FAILED",
                        "email": str(email).strip().lower(),
                        "reason": "Account deactivated" if (inactive_user and not inactive_user.is_active) else "Invalid credentials",
                    },
                    request=request,
                )
            except Exception:
                pass

            if (
                inactive_user
                and inactive_user.check_password(password)
                and not inactive_user.is_active
            ):
                msg = "Your account has been deactivated. Please contact support."
                if is_ajax:
                    return JsonResponse({"ok": False, "error": msg}, status=403)
                messages.error(request, msg)
                return render(request, "pages/login.html", {"email": email})

            if is_ajax:
                return JsonResponse({"ok": False, "error": "Invalid email or password. Please try again."}, status=401)
            messages.error(request, "Invalid email or password. Please try again.")



    context = {}
    reason = request.GET.get("reason", "").strip().lower()
    has_signout_cookie = (
        request.COOKIES.get("ps360_just_logged_out") == "1"
        or request.COOKIES.get("ps360_user_signed_out") == "1"
    )
    if reason == "another_tab":
        context["session_expired_notice"] = (
            "Your account was signed into in another tab or window. This session has been closed for security."
        )
    elif reason == "inactivity" or request.GET.get("session_expired") == "1":
        context["session_expired_notice"] = (
            "Your session timed out after 5 minutes of inactivity. Please sign in again."
        )
    elif reason in ["signed_out", "logged_out", "back_navigation", "logout"] or has_signout_cookie:
        context["session_expired_notice"] = (
            "You have been signed out of your session."
        )
    response = render(request, "pages/login.html", context)
    if has_signout_cookie:
        response.delete_cookie("ps360_just_logged_out")
        response.delete_cookie("ps360_user_signed_out")
    return response





@login_required

def change_password_view(request):

    """

    Renders and processes the password change form.

    Mandatory on first login for users created by Super Admin with must_change_password=True.

    """

    if request.method == "POST":

        form = PasswordChangeForm(request.user, request.POST)

        if form.is_valid():

            user = form.save()

            user.must_change_password = False

            user.save(update_fields=["must_change_password"])

            update_session_auth_hash(request, user)  # Keep user session active



            from apps.audit.models import AuditLog
            from apps.audit.services import create_audit_log_service



            create_audit_log_service(

                actor=user,

                action=AuditLog.ACTION_UPDATE,

                target_model="User",

                target_object_id=str(user.id),

                previous_state={"must_change_password": True},

                new_state={"must_change_password": False, "action": "first_login_password_change"},

                ip_address=request.META.get("REMOTE_ADDR"),

                user_agent=request.META.get("HTTP_USER_AGENT", ""),

            )



            messages.success(

                request,

                "Your password has been changed successfully. Welcome to ProcureSphere 360!",

            )

            from apps.core.views import get_dashboard_url_for_user
            return redirect(get_dashboard_url_for_user(request.user))

        else:

            messages.error(request, "Please correct the password errors below.")

    else:

        form = PasswordChangeForm(request.user)



    return render(

        request,

        "accounts/change_password.html",

        {

            "form": form,

            "is_forced": getattr(request.user, "must_change_password", False),

        },

    )





@never_cache
def portal_logout_view(request):

    """

    Logs out the user from the ERP Portal and redirects to the public landing page (/).
    Supports both POST and GET methods to guarantee reliable signout from modal forms,
    history navigation guards, and direct user actions.

    """
    user = request.user if request.user.is_authenticated else None

    if user:

        from apps.audit.models import AuditLog
        from apps.audit.services import create_audit_log_service



        try:
            create_audit_log_service(

                actor=user,

                action=AuditLog.ACTION_LOGOUT,

                target_model="User",

                target_object_id=str(user.id),

                previous_state={"email": user.email},

            )
        except Exception:
            pass



    logout(request)

    reason = request.GET.get("reason") or request.POST.get("reason")
    if reason in ["signed_out", "modal", "back_navigation", "browser_exit"]:
        response = redirect("/login/?reason=signed_out")
        response.set_cookie("ps360_just_logged_out", "1", max_age=120, path="/", samesite="Lax")
        response.set_cookie("ps360_user_signed_out", "1", max_age=120, path="/", samesite="Lax")
        return response

    if reason == "new_tab":
        messages.info(request, "Your previous session expired due to multiple active tabs. Please sign in again.")
        return redirect("/login/?session_expired=1")

    if reason == "inactivity":
        response = redirect("/login/?session_expired=1")
        response.set_cookie("ps360_just_logged_out", "1", max_age=120, path="/", samesite="Lax")
        return response

    messages.info(request, "You have been logged out successfully.")

    response = redirect("/?logged_out=1")
    response.set_cookie("ps360_just_logged_out", "1", max_age=120, path="/", samesite="Lax")
    return response





@login_required(login_url="/login/")

def password_change_view(request):

    """Lets a user replace their password; mandatory on first login with a temporary password."""

    forced = request.user.must_change_password

    form = SetPasswordForm(request.user, request.POST or None)

    if request.method == "POST":

        current = request.POST.get("current_password", "")

        if not request.user.check_password(current):

            form.add_error(None, "Current (temporary) password is incorrect.")

        elif form.is_valid() and not form.errors:

            user = form.save()

            user.must_change_password = False

            user.save(update_fields=["must_change_password"])

            update_session_auth_hash(request, user)



            from apps.audit.models import AuditLog
            from apps.audit.services import create_audit_log_service



            create_audit_log_service(

                actor=user,

                action=AuditLog.ACTION_UPDATE,

                target_model="User",

                target_object_id=str(user.id),

                previous_state={"must_change_password": forced},

                new_state={"must_change_password": False, "event": "password_changed"},

                ip_address=request.META.get("REMOTE_ADDR"),

                user_agent=request.META.get("HTTP_USER_AGENT", ""),

            )

            messages.success(request, "Password updated.")

            from apps.core.views import get_dashboard_url_for_user
            return redirect(get_dashboard_url_for_user(request.user))

    return render(request, "pages/password_change.html", {"form": form, "forced": forced})





# Aliases for route compatibility

login_page_view = portal_login_view

logout_page_view = portal_logout_view

