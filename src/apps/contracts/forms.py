from decimal import Decimal
from django import forms

from apps.orders.models import PurchaseOrder
from apps.sourcing.models import SourcingEvent
from apps.vendors.models import Vendor

from .models import Contract, ContractDocument, ContractMilestone, ContractObligation

# Sensible enterprise financial limits for contract agreements
MAX_CONTRACT_VALUE = Decimal("1000000000.00")  # ₹1 Billion / 100 Crore enterprise ceiling
MIN_CONTRACT_VALUE = Decimal("0.01")


def validate_contract_value_amount(val):
    """
    Validates that contract financial values adhere to strict financial ERP business rules:
    1. Must be greater than zero.
    2. Cannot exceed the maximum corporate ceiling of ₹1,000,000,000.00 (1 Billion).
    3. Rejects repetitive dummy digit sequences (e.g., 111111, 111111111, 999999999).
    """
    if val is None:
        return val
    if val <= Decimal("0.00"):
        raise forms.ValidationError("Contract value must be greater than zero.")
    if val > MAX_CONTRACT_VALUE:
        raise forms.ValidationError(
            f"Contract value cannot exceed ₹{MAX_CONTRACT_VALUE:,.2f} (1 Billion). Please enter a realistic enterprise contract amount."
        )
    # Reject dummy repeating digits sequences (e.g. 111111, 111111111, 999999999)
    try:
        val_int_str = str(int(val))
        if len(val_int_str) >= 6 and len(set(val_int_str)) == 1:
            raise forms.ValidationError(
                "Contract value cannot be a repeating sequence of identical digits (e.g., 111111111). Please enter a valid financial amount."
            )
    except (ValueError, TypeError):
        pass
    return val


class VendorContractChoiceField(forms.ModelChoiceField):
    """
    Clean formatted dropdown label for Vendor selection in Contract drafting.
    Omits raw status tags like [ACTIVE], [SUSPENDED] for clean, enterprise UI presentation.
    """

    def label_from_instance(self, obj):
        if getattr(obj, "vendor_number", None):
            return f"{obj.legal_name} ({obj.vendor_number})"
        return str(obj.legal_name)


class ContractCreateForm(forms.ModelForm):
    vendor = VendorContractChoiceField(
        queryset=Vendor.objects.exclude(
            status__in=[Vendor.STATUS_SUSPENDED, Vendor.STATUS_REJECTED]
        ).order_by("legal_name"),
        widget=forms.Select(attrs={"class": "form-select", "data-placeholder": "Search and select vendor..."}),
        required=True,
        empty_label="-- Select Active Vendor --",
    )
    sourcing_event = forms.ModelChoiceField(
        queryset=SourcingEvent.objects.all(),
        widget=forms.Select(attrs={"class": "form-select"}),
        required=False,
        empty_label="-- Select Sourcing Event (Optional) --",
    )
    po = forms.ModelChoiceField(
        queryset=PurchaseOrder.objects.all(),
        widget=forms.Select(attrs={"class": "form-select"}),
        required=False,
        empty_label="-- Select Purchase Order (Optional) --",
    )

    class Meta:
        model = Contract
        fields = [
            "title",
            "vendor",
            "sourcing_event",
            "po",
            "contract_value",
            "start_date",
            "end_date",
            "renewal_notice_days",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g., Enterprise IT Infrastructure Maintenance SLA",
                }
            ),
            "contract_value": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0.01",
                    "max": "1000000000.00",
                    "placeholder": "0.00",
                }
            ),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "renewal_notice_days": forms.NumberInput(
                attrs={"class": "form-control", "value": "30"}
            ),
        }

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if len(title) < 5:
            raise forms.ValidationError("Contract title must be at least 5 characters long.")
        if len(set(title.lower())) == 1 and len(title) >= 5:
            raise forms.ValidationError(
                "Contract title cannot be a repeating sequence of identical characters (e.g., 111111). Please enter a meaningful title."
            )
        return title

    def clean_contract_value(self):
        val = self.cleaned_data.get("contract_value")
        return validate_contract_value_amount(val)

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if start_date and end_date and end_date < start_date:
            raise forms.ValidationError("Contract end date cannot be earlier than start date.")
        return cleaned_data


class ContractAmendmentForm(forms.Form):
    amendment_summary = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "State scope change, price adjustment, or term extension details...",
            }
        ),
        required=True,
    )
    contract_value = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=MIN_CONTRACT_VALUE,
        max_value=MAX_CONTRACT_VALUE,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "0.01", "min": "0.01", "max": "1000000000.00"}
        ),
        required=True,
    )
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}), required=True
    )
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}), required=True
    )

    def clean_contract_value(self):
        val = self.cleaned_data.get("contract_value")
        return validate_contract_value_amount(val)

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            raise forms.ValidationError("Contract end date cannot be earlier than start date.")
        return cleaned_data


class ContractMilestoneForm(forms.ModelForm):
    class Meta:
        model = ContractMilestone
        fields = ["title", "due_date", "amount"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g., Phase 1 Implementation Acceptance",
                }
            ),
            "due_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }


RESPONSIBLE_PARTY_CHOICES = [
    ("LEGAL", "Legal Team (LEGAL)"),
    ("VENDOR", "Vendor (VENDOR)"),
    ("BUYER", "Buyer / Client (BUYER)"),
    ("INTERNAL", "Internal Team (INTERNAL)"),
    ("PROCUREMENT", "Procurement (PROCUREMENT)"),
    ("MUTUAL", "Mutual Responsibility (MUTUAL)"),
    ("BOTH", "Both Parties (BOTH)"),
]


class ContractObligationForm(forms.ModelForm):
    RESPONSIBLE_PARTY_CHOICES = RESPONSIBLE_PARTY_CHOICES

    class Meta:
        model = ContractObligation
        fields = ["title", "responsible_party", "due_date"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g., Monthly SLA Uptime Report Submission",
                }
            ),
            "responsible_party": forms.Select(
                choices=RESPONSIBLE_PARTY_CHOICES,
                attrs={"class": "form-select"},
            ),
            "due_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }


class ContractDocumentForm(forms.ModelForm):
    class Meta:
        model = ContractDocument
        fields = ["title", "file"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g., Executed Master Service Agreement PDF",
                }
            ),
            "file": forms.FileInput(attrs={"class": "form-control"}),
        }

    def clean_file(self):
        file = self.cleaned_data.get("file")
        if file:
            ext = file.name.split(".")[-1].lower()
            allowed_extensions = [
                "pdf",
                "docx",
                "doc",
                "xlsx",
                "xls",
                "png",
                "jpg",
                "jpeg",
                "txt",
            ]
            if ext not in allowed_extensions:
                raise forms.ValidationError(
                    f"Unsupported file format '.{ext}'. Allowed formats: PDF, DOCX, XLSX, PNG, JPG, TXT."
                )
            if file.size > 10 * 1024 * 1024:
                raise forms.ValidationError("File size exceeds 10MB upload limit.")
        return file


class ContractRenewalForm(forms.Form):
    new_end_date = forms.DateField(
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}), required=True
    )
    new_value = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=MIN_CONTRACT_VALUE,
        max_value=MAX_CONTRACT_VALUE,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "0.01", "min": "0.01", "max": "1000000000.00"}
        ),
        required=False,
    )
    notes = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Renewal terms & approval notes...",
            }
        ),
        required=False,
    )

    def clean_new_value(self):
        val = self.cleaned_data.get("new_value")
        if val is not None:
            return validate_contract_value_amount(val)
        return val
