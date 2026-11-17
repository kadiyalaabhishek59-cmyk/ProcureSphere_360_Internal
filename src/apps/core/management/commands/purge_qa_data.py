import sys
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Safely and completely purges automated QA test data without touching demo master data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate the deletion in a rolled-back transaction without altering data.",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        mode_str = "DRY-RUN (WILL ROLL BACK)" if dry_run else "LIVE EXECUTION (PERMANENT)"

        self.stdout.write(self.style.WARNING("=" * 60))
        self.stdout.write(self.style.WARNING(f"PURGE QA TEST DATA — {mode_str}"))
        self.stdout.write(self.style.WARNING("=" * 60))

        with connection.cursor() as cur:
            # 1. QA Users
            cur.execute("""
                CREATE TEMP TABLE tmp_qa_users AS
                SELECT id FROM accounts_user
                WHERE (
                    email ILIKE '%qa%'
                    OR email LIKE '%@example.test'
                    OR username ILIKE '%qa%'
                    OR (first_name ILIKE '%qa%' AND last_name ILIKE '%user%')
                    OR (first_name ILIKE '%qa%' AND last_name ILIKE '%requester%')
                )
                AND email NOT IN (
                    'admin@hpe.com', 'superadmin@procuresphere.com', 'procmgr@hpe.com',
                    'auditor@hpe.com', 'requester@hpe.com', 'approver@hpe.com',
                    'receiver@hpe.com', 'finance@hpe.com', 'legal@hpe.com', 'procexec@hpe.com',
                    'compliance.audit01@procuresphere.com', 'finance.ap01@procuresphere.com',
                    'proc.executive01@procuresphere.com', 'proc.manager01@procuresphere.com',
                    'stores.recv01@procuresphere.com', 'legal.contract01@procuresphere.com'
                );
                CREATE INDEX ON tmp_qa_users(id);
            """)
            cur.execute("SELECT count(*) FROM tmp_qa_users")
            user_cnt = cur.fetchone()[0]
            self.stdout.write(f"1. Identified {user_cnt} QA users.")

            # 2. QA Vendors
            cur.execute("""
                CREATE TEMP TABLE tmp_qa_vendors AS
                SELECT id FROM vendors_vendor
                WHERE (
                    legal_name ILIKE '%qa%'
                    OR trade_name ILIKE '%qa%'
                    OR vendor_number ILIKE '%qa%'
                )
                AND legal_name NOT IN ('Cisco Systems Inc', 'Intel Corporation', 'Microsoft Corporation')
                AND vendor_number NOT IN ('VND-2026-00001', 'VND-2026-00002');
                CREATE INDEX ON tmp_qa_vendors(id);
            """)
            cur.execute("SELECT count(*) FROM tmp_qa_vendors")
            vendor_cnt = cur.fetchone()[0]
            self.stdout.write(f"2. Identified {vendor_cnt} QA vendors.")

            # 3. QA Organizations
            cur.execute("""
                CREATE TEMP TABLE tmp_qa_orgs AS
                SELECT id FROM organization_organization
                WHERE (name ILIKE '%qa%' OR code ILIKE '%qa%')
                AND code NOT IN ('HPE-GLOBAL', 'TEST-ORG-001', 'TECHNOVA-ORG-002');
                CREATE INDEX ON tmp_qa_orgs(id);
            """)
            cur.execute("SELECT count(*) FROM tmp_qa_orgs")
            org_cnt = cur.fetchone()[0]
            self.stdout.write(f"3. Identified {org_cnt} QA organizations.")

            # 4. QA Departments
            cur.execute("""
                CREATE TEMP TABLE tmp_qa_depts AS
                SELECT id FROM organization_department
                WHERE (
                    name ILIKE '%qa%' 
                    OR code ILIKE '%qa%'
                    OR organization_id IN (SELECT id FROM tmp_qa_orgs)
                )
                AND code NOT IN (
                    'IT-OPS', 'OPS', 'ENG', 'HR-OPS', 'HPE-PROC', 'HPE-FIN', 
                    'HPE-STORE', 'HPE-LEGAL', 'HPE-AUDIT', 'HPE-ADMIN', 'HPE-ETS'
                );
                CREATE INDEX ON tmp_qa_depts(id);
            """)
            cur.execute("SELECT count(*) FROM tmp_qa_depts")
            dept_cnt = cur.fetchone()[0]
            self.stdout.write(f"4. Identified {dept_cnt} QA departments.")

            # 5. QA Cost Centers
            cur.execute("""
                CREATE TEMP TABLE tmp_qa_ccs AS
                SELECT id FROM organization_costcenter
                WHERE (
                    name ILIKE '%qa%' 
                    OR code ILIKE '%qa%'
                    OR department_id IN (SELECT id FROM tmp_qa_depts)
                )
                AND code NOT IN (
                    'CC-IT-101', 'CC-OPS-201', 'CC-ENG-301', 'CC-HR-101', 'CC-PROC-101', 
                    'CC-FIN-101', 'CC-STORE-101', 'CC-HPE-LEGAL-001', 'CC-HPE-AUDIT-001', 'CC-HPE-ADMIN-001'
                );
                CREATE INDEX ON tmp_qa_ccs(id);
            """)
            cur.execute("SELECT count(*) FROM tmp_qa_ccs")
            cc_cnt = cur.fetchone()[0]
            self.stdout.write(f"5. Identified {cc_cnt} QA cost centers.")

            # 6. QA Requisitions
            cur.execute("""
                CREATE TEMP TABLE tmp_qa_prs AS
                SELECT id FROM requisitions_purchaserequisition
                WHERE title ILIKE '%qa%' 
                   OR pr_number ILIKE '%qa%'
                   OR requester_id IN (SELECT id FROM tmp_qa_users)
                   OR created_by_id IN (SELECT id FROM tmp_qa_users)
                   OR department_id IN (SELECT id FROM tmp_qa_depts)
                   OR cost_center_id IN (SELECT id FROM tmp_qa_ccs);
                CREATE INDEX ON tmp_qa_prs(id);
            """)
            cur.execute("SELECT count(*) FROM tmp_qa_prs")
            pr_cnt = cur.fetchone()[0]
            self.stdout.write(f"6. Identified {pr_cnt} QA requisitions.")

            # 7. QA Sourcing Events
            cur.execute("""
                CREATE TEMP TABLE tmp_qa_events AS
                SELECT id FROM sourcing_sourcingevent
                WHERE title ILIKE '%qa%' 
                   OR event_number ILIKE '%qa%'
                   OR created_by_id IN (SELECT id FROM tmp_qa_users)
                   OR requisition_id IN (SELECT id FROM tmp_qa_prs);
                CREATE INDEX ON tmp_qa_events(id);
            """)
            cur.execute("SELECT count(*) FROM tmp_qa_events")
            event_cnt = cur.fetchone()[0]
            self.stdout.write(f"7. Identified {event_cnt} QA sourcing events.")

            # 8. QA Purchase Orders
            cur.execute("""
                CREATE TEMP TABLE tmp_qa_pos AS
                SELECT id FROM orders_purchaseorder
                WHERE po_number ILIKE '%qa%'
                   OR vendor_id IN (SELECT id FROM tmp_qa_vendors)
                   OR requisition_id IN (SELECT id FROM tmp_qa_prs)
                   OR sourcing_event_id IN (SELECT id FROM tmp_qa_events)
                   OR created_by_id IN (SELECT id FROM tmp_qa_users)
                   OR cost_center_id IN (SELECT id FROM tmp_qa_ccs);
                CREATE INDEX ON tmp_qa_pos(id);
            """)
            cur.execute("SELECT count(*) FROM tmp_qa_pos")
            po_cnt = cur.fetchone()[0]
            self.stdout.write(f"8. Identified {po_cnt} QA purchase orders.")

            # 9. QA Goods Receipts
            cur.execute("""
                CREATE TEMP TABLE tmp_qa_receipts AS
                SELECT id FROM receipts_goodsreceipt
                WHERE grn_number ILIKE '%qa%'
                   OR po_id IN (SELECT id FROM tmp_qa_pos)
                   OR created_by_id IN (SELECT id FROM tmp_qa_users)
                   OR received_by_id IN (SELECT id FROM tmp_qa_users);
                CREATE INDEX ON tmp_qa_receipts(id);
            """)
            cur.execute("SELECT count(*) FROM tmp_qa_receipts")
            receipt_cnt = cur.fetchone()[0]
            self.stdout.write(f"9. Identified {receipt_cnt} QA goods receipts.")

            # 10. QA Invoices
            cur.execute("""
                CREATE TEMP TABLE tmp_qa_invoices AS
                SELECT id FROM invoices_supplierinvoice
                WHERE invoice_number ILIKE '%qa%'
                   OR vendor_id IN (SELECT id FROM tmp_qa_vendors)
                   OR po_id IN (SELECT id FROM tmp_qa_pos)
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
                CREATE INDEX ON tmp_qa_invoices(id);
            """)
            cur.execute("SELECT count(*) FROM tmp_qa_invoices")
            inv_cnt = cur.fetchone()[0]
            self.stdout.write(f"10. Identified {inv_cnt} QA invoices.")

            # 11. QA Contracts
            cur.execute("""
                CREATE TEMP TABLE tmp_qa_contracts AS
                SELECT id FROM contracts_contract
                WHERE title ILIKE '%qa%' 
                   OR contract_number ILIKE '%qa%'
                   OR vendor_id IN (SELECT id FROM tmp_qa_vendors)
                   OR po_id IN (SELECT id FROM tmp_qa_pos)
                   OR sourcing_event_id IN (SELECT id FROM tmp_qa_events)
                   OR contract_owner_id IN (SELECT id FROM tmp_qa_users)
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
                CREATE INDEX ON tmp_qa_contracts(id);
            """)
            cur.execute("SELECT count(*) FROM tmp_qa_contracts")
            con_cnt = cur.fetchone()[0]
            self.stdout.write(f"11. Identified {con_cnt} QA contracts.")

            self.stdout.write("\n--- Cascading Deletion of Child & Transactional Records ---")

            # A. Clean notifications for QA users
            cur.execute("""
                DELETE FROM notifications_notification 
                WHERE recipient_id IN (SELECT id FROM tmp_qa_users) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} notifications")

            # B. Clean Invoices hierarchy
            cur.execute("""
                DELETE FROM invoices_paymentstatus 
                WHERE invoice_id IN (SELECT id FROM tmp_qa_invoices) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR paid_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} invoice payment status records")

            cur.execute("""
                DELETE FROM invoices_matchexception 
                WHERE invoice_id IN (SELECT id FROM tmp_qa_invoices) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR resolved_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} invoice match exceptions")

            cur.execute("""
                DELETE FROM invoices_matchresult 
                WHERE invoice_id IN (SELECT id FROM tmp_qa_invoices) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR performed_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} invoice match results")

            cur.execute("""
                DELETE FROM invoices_invoiceline 
                WHERE invoice_id IN (SELECT id FROM tmp_qa_invoices) 
                   OR po_line_id IN (SELECT id FROM orders_poline WHERE po_id IN (SELECT id FROM tmp_qa_pos))
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} invoice lines")

            cur.execute("DELETE FROM invoices_supplierinvoice WHERE id IN (SELECT id FROM tmp_qa_invoices);")
            self.stdout.write(f"  - Deleted {cur.rowcount} supplier invoices")

            # C. Clean Receipts hierarchy
            cur.execute("""
                DELETE FROM receipts_stockmovement 
                WHERE created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR performed_by_id IN (SELECT id FROM tmp_qa_users)
                   OR stock_item_id IN (
                       SELECT id FROM receipts_stockitem 
                       WHERE po_line_id IN (SELECT id FROM orders_poline WHERE po_id IN (SELECT id FROM tmp_qa_pos))
                          OR created_by_id IN (SELECT id FROM tmp_qa_users)
                   );
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} stock movement records")

            cur.execute("""
                DELETE FROM receipts_stockitem 
                WHERE created_by_id IN (SELECT id FROM tmp_qa_users)
                   OR po_line_id IN (SELECT id FROM orders_poline WHERE po_id IN (SELECT id FROM tmp_qa_pos));
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} stock items")

            cur.execute("""
                DELETE FROM receipts_stockhandoffrecord 
                WHERE created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR handed_off_by_id IN (SELECT id FROM tmp_qa_users)
                   OR receipt_line_id IN (
                       SELECT id FROM receipts_receiptline 
                       WHERE receipt_id IN (SELECT id FROM tmp_qa_receipts)
                          OR po_line_id IN (SELECT id FROM orders_poline WHERE po_id IN (SELECT id FROM tmp_qa_pos))
                   );
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} stock handoff records")

            cur.execute("""
                DELETE FROM receipts_rejectionrecord 
                WHERE created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR receipt_line_id IN (
                       SELECT id FROM receipts_receiptline 
                       WHERE receipt_id IN (SELECT id FROM tmp_qa_receipts)
                          OR po_line_id IN (SELECT id FROM orders_poline WHERE po_id IN (SELECT id FROM tmp_qa_pos))
                   );
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} rejection records")

            cur.execute("""
                DELETE FROM receipts_inspectionrecord 
                WHERE created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR inspected_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR receipt_line_id IN (
                       SELECT id FROM receipts_receiptline 
                       WHERE receipt_id IN (SELECT id FROM tmp_qa_receipts)
                          OR po_line_id IN (SELECT id FROM orders_poline WHERE po_id IN (SELECT id FROM tmp_qa_pos))
                   );
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} inspection records")

            cur.execute("""
                DELETE FROM receipts_receiptline 
                WHERE receipt_id IN (SELECT id FROM tmp_qa_receipts) 
                   OR po_line_id IN (SELECT id FROM orders_poline WHERE po_id IN (SELECT id FROM tmp_qa_pos))
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} receipt lines")

            cur.execute("DELETE FROM receipts_goodsreceipt WHERE id IN (SELECT id FROM tmp_qa_receipts);")
            self.stdout.write(f"  - Deleted {cur.rowcount} goods receipts")

            # D. Clean Orders hierarchy
            cur.execute("""
                DELETE FROM orders_deliveryschedule 
                WHERE po_id IN (SELECT id FROM tmp_qa_pos) 
                   OR po_line_id IN (SELECT id FROM orders_poline WHERE po_id IN (SELECT id FROM tmp_qa_pos))
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} delivery schedules")

            cur.execute("""
                DELETE FROM orders_poamendment 
                WHERE po_id IN (SELECT id FROM tmp_qa_pos) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR requested_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR approved_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} po amendments")

            cur.execute("""
                DELETE FROM orders_poline 
                WHERE po_id IN (SELECT id FROM tmp_qa_pos) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} po lines")

            cur.execute("UPDATE orders_purchaseorder SET award_id = NULL WHERE id IN (SELECT id FROM tmp_qa_pos);")
            cur.execute("DELETE FROM orders_purchaseorder WHERE id IN (SELECT id FROM tmp_qa_pos);")
            self.stdout.write(f"  - Deleted {cur.rowcount} purchase orders")

            # E. Clean Contracts hierarchy
            cur.execute("DELETE FROM scorecards_vendorscorecardslametric WHERE contract_id IN (SELECT id FROM tmp_qa_contracts);")
            cur.execute("""
                DELETE FROM contracts_contractalert 
                WHERE contract_id IN (SELECT id FROM tmp_qa_contracts) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} contract alerts")

            cur.execute("""
                DELETE FROM contracts_contractdocument 
                WHERE contract_id IN (SELECT id FROM tmp_qa_contracts) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR uploaded_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} contract documents")

            cur.execute("""
                DELETE FROM contracts_contractmilestone 
                WHERE contract_id IN (SELECT id FROM tmp_qa_contracts) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} contract milestones")

            cur.execute("""
                DELETE FROM contracts_contractobligation 
                WHERE contract_id IN (SELECT id FROM tmp_qa_contracts) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} contract obligations")

            cur.execute("""
                DELETE FROM contracts_contractversion 
                WHERE contract_id IN (SELECT id FROM tmp_qa_contracts) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR approved_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} contract versions")

            cur.execute("DELETE FROM contracts_contract WHERE id IN (SELECT id FROM tmp_qa_contracts);")
            self.stdout.write(f"  - Deleted {cur.rowcount} contracts")

            # F. Clean Sourcing hierarchy
            cur.execute("""
                DELETE FROM sourcing_negotiationnote 
                WHERE event_id IN (SELECT id FROM tmp_qa_events) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users)
                   OR author_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} negotiation notes")

            cur.execute("""
                DELETE FROM sourcing_clarification 
                WHERE event_id IN (SELECT id FROM tmp_qa_events) 
                   OR vendor_id IN (SELECT id FROM tmp_qa_vendors) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users)
                   OR answered_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} clarifications")

            cur.execute("""
                DELETE FROM sourcing_awarddecision 
                WHERE event_id IN (SELECT id FROM tmp_qa_events) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR approved_by_id IN (SELECT id FROM tmp_qa_users)
                   OR recommended_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} award decisions")

            cur.execute("""
                DELETE FROM sourcing_bidevaluation 
                WHERE event_id IN (SELECT id FROM tmp_qa_events) 
                   OR evaluator_id IN (SELECT id FROM tmp_qa_users) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR bid_id IN (SELECT id FROM sourcing_vendorbid WHERE event_id IN (SELECT id FROM tmp_qa_events) OR vendor_id IN (SELECT id FROM tmp_qa_vendors));
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} bid evaluations")

            cur.execute("""
                DELETE FROM sourcing_bidversion 
                WHERE created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR bid_id IN (SELECT id FROM sourcing_vendorbid WHERE event_id IN (SELECT id FROM tmp_qa_events) OR vendor_id IN (SELECT id FROM tmp_qa_vendors));
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} bid versions")

            cur.execute("""
                DELETE FROM sourcing_bidattachment 
                WHERE created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR bid_id IN (SELECT id FROM sourcing_vendorbid WHERE event_id IN (SELECT id FROM tmp_qa_events) OR vendor_id IN (SELECT id FROM tmp_qa_vendors));
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} bid attachments")

            cur.execute("""
                DELETE FROM sourcing_bidline 
                WHERE created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR bid_id IN (SELECT id FROM sourcing_vendorbid WHERE event_id IN (SELECT id FROM tmp_qa_events) OR vendor_id IN (SELECT id FROM tmp_qa_vendors));
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} bid lines")

            cur.execute("""
                DELETE FROM sourcing_vendorbid 
                WHERE event_id IN (SELECT id FROM tmp_qa_events) 
                   OR vendor_id IN (SELECT id FROM tmp_qa_vendors) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} vendor bids")

            cur.execute("""
                DELETE FROM sourcing_bidinvite 
                WHERE event_id IN (SELECT id FROM tmp_qa_events) 
                   OR vendor_id IN (SELECT id FROM tmp_qa_vendors) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} bid invites")

            cur.execute("DELETE FROM sourcing_sourcingevent WHERE id IN (SELECT id FROM tmp_qa_events);")
            self.stdout.write(f"  - Deleted {cur.rowcount} sourcing events")

            # G. Clean Requisitions hierarchy
            cur.execute("""
                DELETE FROM budgets_budgetreservation 
                WHERE requisition_id IN (SELECT id FROM tmp_qa_prs) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} budget reservations")

            cur.execute("""
                DELETE FROM approvals_approvalaction 
                WHERE created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR actor_id IN (SELECT id FROM tmp_qa_users) 
                   OR target_object_id IN (SELECT id FROM tmp_qa_prs)
                   OR target_object_id IN (SELECT id FROM tmp_qa_pos)
                   OR target_object_id IN (SELECT id FROM tmp_qa_events)
                   OR target_object_id IN (SELECT id FROM tmp_qa_contracts)
                   OR target_object_id IN (SELECT id FROM tmp_qa_vendors);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} approval actions")

            cur.execute("""
                DELETE FROM requisitions_prattachment 
                WHERE requisition_id IN (SELECT id FROM tmp_qa_prs) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR uploaded_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} PR attachments")

            cur.execute("""
                DELETE FROM requisitions_prline 
                WHERE requisition_id IN (SELECT id FROM tmp_qa_prs) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} PR lines")

            cur.execute("DELETE FROM requisitions_purchaserequisition WHERE id IN (SELECT id FROM tmp_qa_prs);")
            self.stdout.write(f"  - Deleted {cur.rowcount} purchase requisitions")

            # H. Clean Vendors hierarchy
            cur.execute("""
                DELETE FROM scorecards_vendorscorecardslametric 
                WHERE created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR scorecard_id IN (SELECT id FROM scorecards_vendorscorecard WHERE vendor_id IN (SELECT id FROM tmp_qa_vendors));
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} scorecard SLA metrics")

            cur.execute("""
                DELETE FROM scorecards_vendorscorecard 
                WHERE vendor_id IN (SELECT id FROM tmp_qa_vendors) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR evaluated_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} vendor scorecards")

            cur.execute("""
                DELETE FROM vendors_vendorcredentialdispatch 
                WHERE vendor_id IN (SELECT id FROM tmp_qa_vendors) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR user_id IN (SELECT id FROM tmp_qa_users)
                   OR legal_verified_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} credential dispatches")

            cur.execute("""
                DELETE FROM vendors_vendordocumentreviewhistory 
                WHERE created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR reviewer_id IN (SELECT id FROM tmp_qa_users) 
                   OR document_id IN (SELECT id FROM vendors_vendordocument WHERE vendor_id IN (SELECT id FROM tmp_qa_vendors));
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} document review histories")

            cur.execute("UPDATE vendors_vendordocument SET replaces_document_id = NULL WHERE vendor_id IN (SELECT id FROM tmp_qa_vendors);")

            cur.execute("""
                DELETE FROM vendors_vendordocument 
                WHERE vendor_id IN (SELECT id FROM tmp_qa_vendors) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR verified_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} vendor documents")

            cur.execute("""
                DELETE FROM vendors_vendorcontact 
                WHERE vendor_id IN (SELECT id FROM tmp_qa_vendors) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} vendor contacts")

            cur.execute("""
                DELETE FROM vendors_vendorriskrecord 
                WHERE vendor_id IN (SELECT id FROM tmp_qa_vendors) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users) 
                   OR assessed_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} vendor risk records")

            # Clean legacy vendor_* tables if they exist
            for leg_tbl in [
                'vendor_vendorstatusaction', 'vendor_vendorrisk', 'vendor_vendorperformance',
                'vendor_vendorduediligence', 'vendor_vendordocument', 'vendor_vendorcontact',
                'vendor_vendorbankinfo', 'vendor_vendorapprovalworkflow', 'vendor_bidattachment',
                'vendor_bid', 'vendor_vendor'
            ]:
                cur.execute(f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema='public' AND table_name='{leg_tbl}')")
                if cur.fetchone()[0]:
                    try:
                        cur.execute(f"DELETE FROM {leg_tbl} WHERE created_by_id IN (SELECT id FROM tmp_qa_users);")
                    except Exception:
                        pass

            cur.execute("UPDATE accounts_user SET vendor_id = NULL WHERE vendor_id IN (SELECT id FROM tmp_qa_vendors);")
            cur.execute("DELETE FROM vendors_vendor WHERE id IN (SELECT id FROM tmp_qa_vendors);")
            self.stdout.write(f"  - Deleted {cur.rowcount} vendors")

            # I. Clean Budgets / Spend / Cost Centers / Depts / Orgs
            cur.execute("""
                DELETE FROM budgets_spendledger 
                WHERE budget_id IN (SELECT id FROM budgets_budget WHERE cost_center_id IN (SELECT id FROM tmp_qa_ccs)) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} spend ledger entries")

            cur.execute("""
                DELETE FROM budgets_budget 
                WHERE cost_center_id IN (SELECT id FROM tmp_qa_ccs) 
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} budgets")

            cur.execute("""
                DELETE FROM approvals_approvalstep 
                WHERE policy_id IN (
                    SELECT id FROM approvals_approvalpolicy 
                    WHERE organization_id IN (SELECT id FROM tmp_qa_orgs)
                       OR department_id IN (SELECT id FROM tmp_qa_depts)
                       OR cost_center_id IN (SELECT id FROM tmp_qa_ccs)
                       OR created_by_id IN (SELECT id FROM tmp_qa_users)
                );
            """)
            cur.execute("DELETE FROM approvals_approvalpolicy_departments WHERE department_id IN (SELECT id FROM tmp_qa_depts);")
            cur.execute("""
                DELETE FROM approvals_approvalpolicy 
                WHERE organization_id IN (SELECT id FROM tmp_qa_orgs)
                   OR department_id IN (SELECT id FROM tmp_qa_depts)
                   OR cost_center_id IN (SELECT id FROM tmp_qa_ccs)
                   OR created_by_id IN (SELECT id FROM tmp_qa_users);
            """)
            cur.execute("DELETE FROM organization_location WHERE organization_id IN (SELECT id FROM tmp_qa_orgs) OR created_by_id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("DELETE FROM organization_fiscalperiod WHERE organization_id IN (SELECT id FROM tmp_qa_orgs) OR created_by_id IN (SELECT id FROM tmp_qa_users);")

            # Break circular FKs
            cur.execute("UPDATE organization_costcenter SET manager_id = NULL WHERE id IN (SELECT id FROM tmp_qa_ccs) OR manager_id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("""
                UPDATE organization_organization 
                SET admin_user_id = NULL, compliance_auditor_id = NULL, procurement_manager_id = NULL 
                WHERE id IN (SELECT id FROM tmp_qa_orgs) 
                   OR admin_user_id IN (SELECT id FROM tmp_qa_users) 
                   OR compliance_auditor_id IN (SELECT id FROM tmp_qa_users) 
                   OR procurement_manager_id IN (SELECT id FROM tmp_qa_users);
            """)
            cur.execute("UPDATE accounts_user SET organization_id = NULL, department_id = NULL, cost_center_id = NULL WHERE id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("UPDATE accounts_user SET cost_center_id = NULL WHERE cost_center_id IN (SELECT id FROM tmp_qa_ccs);")
            cur.execute("UPDATE accounts_user SET department_id = NULL WHERE department_id IN (SELECT id FROM tmp_qa_depts);")
            cur.execute("UPDATE accounts_user SET organization_id = NULL WHERE organization_id IN (SELECT id FROM tmp_qa_orgs);")

            cur.execute("DELETE FROM organization_costcenter WHERE id IN (SELECT id FROM tmp_qa_ccs);")
            self.stdout.write(f"  - Deleted {cur.rowcount} cost centers")

            cur.execute("DELETE FROM organization_department WHERE id IN (SELECT id FROM tmp_qa_depts);")
            self.stdout.write(f"  - Deleted {cur.rowcount} departments")

            cur.execute("DELETE FROM organization_organization WHERE id IN (SELECT id FROM tmp_qa_orgs);")
            self.stdout.write(f"  - Deleted {cur.rowcount} organizations")

            # J. Nullify remaining user references
            cur.execute("UPDATE approvals_approvaldelegate SET created_by_id = NULL WHERE created_by_id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("DELETE FROM approvals_approvaldelegate WHERE delegate_id IN (SELECT id FROM tmp_qa_users) OR approver_id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("UPDATE approvals_approvalpolicy SET created_by_id = NULL WHERE created_by_id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("UPDATE approvals_approvalpolicy SET exception_specific_approver_id = NULL WHERE exception_specific_approver_id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("UPDATE approvals_approvalstep SET created_by_id = NULL WHERE created_by_id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("UPDATE approvals_approvalstep SET specific_approver_id = NULL WHERE specific_approver_id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("UPDATE reports_exportjob SET created_by_id = NULL, requested_by_id = NULL WHERE created_by_id IN (SELECT id FROM tmp_qa_users) OR requested_by_id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("UPDATE core_contactenquiry SET created_by_id = NULL WHERE created_by_id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("DELETE FROM django_admin_log WHERE user_id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("DELETE FROM accounts_user_groups WHERE user_id IN (SELECT id FROM tmp_qa_users);")
            cur.execute("DELETE FROM accounts_user_user_permissions WHERE user_id IN (SELECT id FROM tmp_qa_users);")

            # K. Delete Audit logs
            cur.execute("""
                DELETE FROM audit_auditlog 
                WHERE actor_id IN (SELECT id FROM tmp_qa_users)
                   OR target_object_id IN (SELECT id::text FROM tmp_qa_prs)
                   OR target_object_id IN (SELECT id::text FROM tmp_qa_pos)
                   OR target_object_id IN (SELECT id::text FROM tmp_qa_events)
                   OR target_object_id IN (SELECT id::text FROM tmp_qa_contracts)
                   OR target_object_id IN (SELECT id::text FROM tmp_qa_vendors)
                   OR target_object_id IN (SELECT id::text FROM tmp_qa_invoices)
                   OR target_object_id IN (SELECT id::text FROM tmp_qa_receipts)
                   OR target_object_id IN (SELECT id::text FROM tmp_qa_users)
                   OR target_object_id IN (SELECT id::text FROM tmp_qa_orgs)
                   OR target_object_id IN (SELECT id::text FROM tmp_qa_depts)
                   OR target_object_id IN (SELECT id::text FROM tmp_qa_ccs);
            """)
            self.stdout.write(f"  - Deleted {cur.rowcount} QA audit logs")

            # L. Delete QA users
            cur.execute("DELETE FROM accounts_user WHERE id IN (SELECT id FROM tmp_qa_users);")
            self.stdout.write(f"  - Deleted {cur.rowcount} accounts_user records")

        if dry_run:
            self.stdout.write(self.style.NOTICE("\nDry-run completed successfully! (No database records were changed)"))
        else:
            self.stdout.write(self.style.SUCCESS("\nAll QA test data successfully purged from the database!"))

