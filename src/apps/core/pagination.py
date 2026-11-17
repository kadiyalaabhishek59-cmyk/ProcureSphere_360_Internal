from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """
    Standard pagination for ProcureSphere 360 REST endpoints.
    Allows clients to pass ?page_size=... up to 1000 items while defaulting to 25.

    When a request is for dropdown options or explicitly disables pagination
    (?paginate=false, ?pagination=none, ?dropdown=true, ?page_size=all),
    pagination is completely bypassed and all eligible records are returned.
    """
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 1000

    def paginate_queryset(self, queryset, request, view=None):
        paginate_param = request.query_params.get("paginate", "").lower()
        pagination_param = request.query_params.get("pagination", "").lower()
        dropdown_param = request.query_params.get("dropdown", "").lower()
        page_size_param = request.query_params.get("page_size", "").lower()

        if (
            paginate_param in ("false", "0", "no")
            or pagination_param in ("none", "false", "0", "no")
            or dropdown_param in ("true", "1", "yes")
            or page_size_param in ("all", "0", "-1")
        ):
            return None

        return super().paginate_queryset(queryset, request, view)
