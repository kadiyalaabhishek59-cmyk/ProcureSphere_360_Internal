from django.db import models
from django.shortcuts import get_object_or_404
from django.urls import path
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter
from rest_framework.views import APIView

from apps.accounts.permissions import IsProcurementManager
from apps.audit.models import AuditLog
from apps.vendors.models import Vendor

from .api_views import (
    BidEvaluationViewSet,
    ClarificationViewSet,
    SourcingEventViewSet,
    VendorBidViewSet,
)
from .models import AwardDecision, SourcingEvent, VendorBid
from .services import evaluate_and_award_sourcing_event_service


def get_user_org(user):
    if user and user.is_authenticated and not user.is_superuser:
        return getattr(user, "effective_organization", None)
    return None


class PendingAwardsAPIView(APIView):
    """
    GET /api/v1/sourcing-events/awards/pending/
    Returns sourcing events for the manager awards desk:
    - Events pending review/award (TECHNICAL_REVIEW, COMMERCIAL_REVIEW, AWARD_APPROVAL, or closed bid windows with bids)
    - Already awarded events (AWARDED)
    - Closed events without bids (NO_BIDS)
    Supports query parameter ?tab=pending|awarded|closed_no_bids|all
    """

    permission_classes = [IsAuthenticated, IsProcurementManager]

    def get(self, request):
        tab = request.query_params.get("tab", "all").strip().lower()
        org = get_user_org(request.user)
        now = timezone.now()

        target_statuses = [
            SourcingEvent.STATUS_AWARD_APPROVAL,
            SourcingEvent.STATUS_COMMERCIAL_REVIEW,
            SourcingEvent.STATUS_TECHNICAL_REVIEW,
            SourcingEvent.STATUS_AWARDED,
            SourcingEvent.STATUS_BID_WINDOW,
            SourcingEvent.STATUS_CANCELLED,
        ]

        events = (
            SourcingEvent.objects.filter(
                status__in=target_statuses,
            )
            .select_related("requisition", "requisition__department", "requisition__cost_center")
            .prefetch_related(
                "bids",
                "bids__vendor",
                "evaluations",
                "evaluations__evaluator",
                "award_decisions",
                "award_decisions__winning_bid",
                "award_decisions__winning_bid__vendor",
                "award_decisions__approved_by",
                "purchase_orders",
            )
            .order_by("-updated_at")
        )
        if org:
            is_hpe_org = org.code in ["ORG-HPE-01", "HPE-GLOBAL"] or "Hewlett Packard" in org.name
            org_filter = (
                models.Q(requisition__department__organization=org)
                | models.Q(requisition__requester__organization=org)
                | models.Q(created_by__organization=org)
                | models.Q(created_by__department__organization=org)
            )
            if is_hpe_org:
                org_filter |= models.Q(requisition__isnull=True, created_by__isnull=True)
            events = events.filter(org_filter)
        elif not request.user.is_superuser:
            events = events.none()

        results = []
        for event in events:
            evaluations_list = list(event.evaluations.all())
            event_bids = list(event.bids.all())
            submitted_bids = [
                b for b in event_bids
                if b.status in [VendorBid.STATUS_SUBMITTED, VendorBid.STATUS_AMENDED]
            ]
            has_bids = len(submitted_bids) > 0
            is_awarded = (event.status == SourcingEvent.STATUS_AWARDED)

            is_window_closed = bool(
                (event.bid_end_date and event.bid_end_date <= now)
                or event.status in [
                    SourcingEvent.STATUS_TECHNICAL_REVIEW,
                    SourcingEvent.STATUS_COMMERCIAL_REVIEW,
                    SourcingEvent.STATUS_AWARD_APPROVAL,
                    SourcingEvent.STATUS_AWARDED,
                    SourcingEvent.STATUS_CANCELLED,
                ]
            )

            if event.status == SourcingEvent.STATUS_BID_WINDOW and not is_window_closed:
                continue

            if is_awarded:
                event_category = "awarded"
            elif not has_bids and is_window_closed:
                event_category = "closed_no_bids"
            elif event.status in [
                SourcingEvent.STATUS_AWARD_APPROVAL,
                SourcingEvent.STATUS_COMMERCIAL_REVIEW,
                SourcingEvent.STATUS_TECHNICAL_REVIEW,
                SourcingEvent.STATUS_BID_WINDOW,
            ] and has_bids:
                event_category = "pending"
            else:
                continue

            if tab == "pending" and event_category != "pending":
                continue
            elif tab == "awarded" and event_category != "awarded":
                continue
            elif tab == "closed_no_bids" and event_category != "closed_no_bids":
                continue

            evaluated_bids = []
            for bid in submitted_bids:
                eval_obj = next((e for e in evaluations_list if e.bid_id == bid.id), None)
                evaluated_bids.append(
                    {
                        "bid_id": str(bid.id),
                        "bid_number": bid.bid_number,
                        "vendor_id": str(bid.vendor.id),
                        "vendor_name": bid.vendor.legal_name,
                        "vendor_status": bid.vendor.status,
                        "is_vendor_suspended": bid.vendor.status == Vendor.STATUS_SUSPENDED,
                        "total_bid_amount": float(bid.total_bid_amount),
                        "version": bid.version,
                        "submitted_at": bid.submitted_at.isoformat() if bid.submitted_at else None,
                        "technical_score": float(eval_obj.technical_score) if eval_obj else 0.0,
                        "commercial_score": float(eval_obj.commercial_score) if eval_obj else 0.0,
                        "weighted_total_score": (
                            float(eval_obj.weighted_total_score) if eval_obj else 0.0
                        ),
                        "evaluation_comments": eval_obj.comments if eval_obj else "",
                    }
                )

            evaluated_bids.sort(key=lambda b: (-b["weighted_total_score"], b["total_bid_amount"]))

            award_info = None
            if is_awarded:
                approved_decision = (
                    event.award_decisions.filter(status=AwardDecision.STATUS_APPROVED).order_by("-decided_at").first()
                    or event.award_decisions.order_by("-created_at").first()
                )
                linked_po = event.purchase_orders.first()
                if approved_decision:
                    w_bid = approved_decision.winning_bid
                    w_vendor = w_bid.vendor if w_bid else None
                    award_info = {
                        "decision_id": str(approved_decision.id),
                        "decision_status": approved_decision.status,
                        "winning_bid_id": str(w_bid.id) if w_bid else None,
                        "winning_bid_number": w_bid.bid_number if w_bid else None,
                        "winning_vendor_id": str(w_vendor.id) if w_vendor else None,
                        "winning_vendor_name": w_vendor.legal_name if w_vendor else "Awarded Supplier",
                        "winning_vendor_number": w_vendor.vendor_number if w_vendor else "",
                        "awarded_amount": float(w_bid.total_bid_amount) if w_bid else 0.0,
                        "awarded_at": approved_decision.decided_at.isoformat() if approved_decision.decided_at else None,
                        "awarded_by": (
                            approved_decision.approved_by.get_full_name()
                            or approved_decision.approved_by.email
                            if approved_decision.approved_by else "Procurement Manager"
                        ),
                        "award_reason": approved_decision.award_reason or approved_decision.decision_comments or "",
                        "po_id": str(linked_po.id) if linked_po else None,
                        "po_number": linked_po.po_number if linked_po else None,
                        "po_status": linked_po.status if linked_po else None,
                    }
                elif evaluated_bids:
                    top_b = evaluated_bids[0]
                    award_info = {
                        "winning_vendor_id": top_b["vendor_id"],
                        "winning_vendor_name": top_b["vendor_name"],
                        "awarded_amount": top_b["total_bid_amount"],
                        "awarded_at": event.updated_at.isoformat() if event.updated_at else None,
                        "awarded_by": "Procurement Manager",
                        "award_reason": "Award approved by executive governance.",
                        "po_id": str(linked_po.id) if linked_po else None,
                        "po_number": linked_po.po_number if linked_po else None,
                        "po_status": linked_po.status if linked_po else None,
                    }

            recommended_bid = None
            if award_info and award_info.get("winning_bid_id"):
                recommended_bid = next(
                    (b for b in evaluated_bids if b["bid_id"] == award_info["winning_bid_id"]),
                    evaluated_bids[0] if evaluated_bids else None,
                )
            elif evaluated_bids:
                recommended_bid = evaluated_bids[0]

            results.append(
                {
                    "id": str(event.id),
                    "event_number": event.event_number,
                    "title": event.title,
                    "event_type": event.event_type,
                    "status": event.status,
                    "event_category": event_category,
                    "is_awarded": is_awarded,
                    "is_closed_no_bids": (event_category == "closed_no_bids"),
                    "has_bids": has_bids,
                    "description": event.description or "",
                    "requisition_id": str(event.requisition.id) if event.requisition else None,
                    "requisition_number": (
                        event.requisition.pr_number if event.requisition else None
                    ),
                    "requisition_title": (event.requisition.title if event.requisition else None),
                    "department": (
                        event.requisition.department.name
                        if event.requisition and event.requisition.department
                        else None
                    ),
                    "cost_center": (
                        event.requisition.cost_center.code
                        if event.requisition and event.requisition.cost_center
                        else None
                    ),
                    "bid_start_date": (
                        event.bid_start_date.isoformat() if event.bid_start_date else None
                    ),
                    "bid_end_date": (
                        event.bid_end_date.isoformat() if event.bid_end_date else None
                    ),
                    "bids_count": len(event_bids),
                    "submitted_bids_count": len(submitted_bids),
                    "evaluations_count": len(evaluations_list),
                    "evaluated_bids": evaluated_bids,
                    "recommended_bid": recommended_bid,
                    "award_decision": award_info,
                }
            )

        return Response(results, status=status.HTTP_200_OK)


class AwardApproveAPIView(APIView):
    """
    POST /api/v1/sourcing-events/events/<uuid:pk>/award-approve/
    Processes Manager Award Decision (APPROVE, REJECT, or RETURN) with audit ledger logging.
    """

    permission_classes = [IsAuthenticated, IsProcurementManager]

    def post(self, request, pk):
        event = get_object_or_404(SourcingEvent, pk=pk)

        org = get_user_org(request.user)
        event_org = (
            event.requisition.department.organization
            if event.requisition and event.requisition.department
            else (
                event.created_by.department.organization
                if event.created_by and event.created_by.department
                else None
            )
        )
        if org and event_org and event_org.id != org.id:
            return Response(
                {
                    "error": {
                        "code": "PERMISSION_DENIED",
                        "message": "Permission denied: Sourcing event belongs to another organization.",
                    }
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if event.status == SourcingEvent.STATUS_AWARDED:
            return Response(
                {
                    "error": {
                        "code": "INVALID_TRANSITION",
                        "message": f"Sourcing Event {event.event_number} is already awarded. Duplicate award approval is prevented.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if event.status not in [
            SourcingEvent.STATUS_AWARD_APPROVAL,
            SourcingEvent.STATUS_COMMERCIAL_REVIEW,
            SourcingEvent.STATUS_TECHNICAL_REVIEW,
            SourcingEvent.STATUS_BID_WINDOW,
        ]:
            return Response(
                {
                    "error": {
                        "code": "INVALID_TRANSITION",
                        "message": f"Sourcing Event in status '{event.status}' cannot be awarded, rejected, or returned.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if event.status == SourcingEvent.STATUS_BID_WINDOW:
            if event.bid_end_date and event.bid_end_date > timezone.now():
                return Response(
                    {
                        "error": {
                            "code": "INVALID_TRANSITION",
                            "message": f"Bid window for {event.event_number} is still open. Bids cannot be awarded until window closes.",
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        action = str(request.data.get("action", "APPROVE")).upper()
        comments = str(request.data.get("comments", request.data.get("award_reason", ""))).strip()

        if action == "APPROVE":
            winning_bid_id = request.data.get("winning_bid_id")
            if winning_bid_id:
                winning_bid = event.bids.filter(
                    id=winning_bid_id,
                    status__in=[VendorBid.STATUS_SUBMITTED, VendorBid.STATUS_AMENDED],
                ).first()
            else:
                top_eval = event.evaluations.order_by("-weighted_total_score").first()
                if top_eval and top_eval.bid.status in [
                    VendorBid.STATUS_SUBMITTED,
                    VendorBid.STATUS_AMENDED,
                ]:
                    winning_bid = top_eval.bid
                else:
                    winning_bid = (
                        event.bids.filter(
                            status__in=[VendorBid.STATUS_SUBMITTED, VendorBid.STATUS_AMENDED]
                        )
                        .order_by("total_bid_amount")
                        .first()
                    )

            if not winning_bid:
                return Response(
                    {
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": "A valid submitted winning bid must be selected for award approval.",
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                decision = evaluate_and_award_sourcing_event_service(
                    event=event,
                    winning_bid=winning_bid,
                    award_reason=comments or "Award approved by Procurement Manager.",
                    approved_by_user=request.user,
                )
                return Response(
                    {
                        "message": f"Sourcing Event {event.event_number} successfully awarded to {winning_bid.vendor.legal_name}.",
                        "event_id": str(event.id),
                        "status": event.status,
                        "winning_bid_id": str(winning_bid.id),
                        "winning_vendor": winning_bid.vendor.legal_name,
                        "award_decision_id": str(decision.id),
                    },
                    status=status.HTTP_200_OK,
                )
            except Exception as e:
                err_msg = (
                    e.messages[0]
                    if hasattr(e, "messages") and e.messages
                    else (e.message if hasattr(e, "message") else str(e))
                )
                if isinstance(err_msg, str) and err_msg.startswith("['") and err_msg.endswith("']"):
                    err_msg = err_msg[2:-2]
                return Response(
                    {"error": {"code": "VALIDATION_ERROR", "message": str(err_msg)}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        elif action in ["REJECT", "RETURN"]:
            if not comments:
                return Response(
                    {
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": "Rejection/return justification comments are mandatory.",
                        }
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            previous_status = event.status
            new_status = (
                SourcingEvent.STATUS_COMMERCIAL_REVIEW
                if action == "RETURN"
                else SourcingEvent.STATUS_CANCELLED
            )
            event.status = new_status
            event.save(update_fields=["status", "updated_at"])

            AuditLog.objects.create(
                actor=request.user,
                action=AuditLog.ACTION_REJECT if action == "REJECT" else AuditLog.ACTION_UPDATE,
                target_model="SourcingEvent",
                target_object_id=str(event.id),
                previous_state={"status": previous_status},
                new_state={"status": event.status, "action": action, "comments": comments},
            )

            return Response(
                {
                    "message": f"Sourcing Event {event.event_number} status updated to {new_status}.",
                    "event_id": str(event.id),
                    "status": event.status,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": f"Invalid action '{action}'. Supported actions: APPROVE, REJECT, RETURN.",
                }
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


@require_http_methods(["GET", "PUT", "PATCH"])
def sourcing_event_direct_detail(request, pk):
    return SourcingEventViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update"})(request, pk=pk)


@require_http_methods(["POST"])
def sourcing_event_direct_publish(request, pk):
    return SourcingEventViewSet.as_view({"post": "publish"})(request, pk=pk)


@require_http_methods(["GET", "POST"])
def sourcing_event_direct_bids(request, pk):
    return SourcingEventViewSet.as_view({"get": "bids", "post": "bids"})(request, pk=pk)


router = DefaultRouter()
router.register(r"events", SourcingEventViewSet, basename="sourcing-event")
router.register(r"bids", VendorBidViewSet, basename="vendor-bid")
router.register(r"clarifications", ClarificationViewSet, basename="sourcing-clarification")
router.register(r"evaluations", BidEvaluationViewSet, basename="bid-evaluation")

urlpatterns = [
    path("awards/pending/", PendingAwardsAPIView.as_view(), name="pending-awards-api"),
    path(
        "events/<uuid:pk>/award-approve/", AwardApproveAPIView.as_view(), name="award-approve-api"
    ),
    path("<uuid:pk>/publish/", sourcing_event_direct_publish, name="sourcing-event-publish-direct"),
    path("<uuid:pk>/publish", sourcing_event_direct_publish),
    path("<uuid:pk>/bids/", sourcing_event_direct_bids, name="sourcing-event-bids-direct"),
    path("<uuid:pk>/bids", sourcing_event_direct_bids),
    path("<uuid:pk>/", sourcing_event_direct_detail, name="sourcing-event-detail-direct"),
    path("<uuid:pk>", sourcing_event_direct_detail),
] + router.urls
