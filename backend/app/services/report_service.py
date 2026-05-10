from app.models.schemas import DecisionAction, ReportSummary
from app.services.graph_builder import graph_service
from app.services.integrator import integration_service
from app.services.textbook_parser import parser_service


class ReportService:
    def summary(self) -> ReportSummary:
        textbooks = parser_service.list_textbooks()
        graph = graph_service.current_graph()
        integration = integration_service.load_result()

        merge_count = sum(1 for d in integration.decisions if d.action == DecisionAction.merge)
        keep_count = sum(1 for d in integration.decisions if d.action == DecisionAction.keep)
        remove_count = sum(1 for d in integration.decisions if d.action == DecisionAction.remove)

        return ReportSummary(
            textbook_count=len(textbooks),
            original_chars=integration.original_chars,
            integrated_chars=integration.integrated_chars,
            compression_ratio=integration.compression_ratio,
            merge_count=merge_count,
            keep_count=keep_count,
            remove_count=remove_count,
        )


report_service = ReportService()
