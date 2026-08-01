CREATE INDEX `idx_calls_org_created` ON `calls` (`organization_id`,`created_at`);--> statement-breakpoint
CREATE INDEX `idx_calls_org_status_created` ON `calls` (`organization_id`,`status`,`created_at`);--> statement-breakpoint
CREATE INDEX `idx_calls_org_seller_created` ON `calls` (`organization_id`,`seller_email`,`created_at`);--> statement-breakpoint
CREATE INDEX `idx_calls_org_followup` ON `calls` (`organization_id`,`followup_required`,`followup_at`);--> statement-breakpoint
CREATE INDEX `idx_evidence_org_call` ON `extraction_evidence` (`organization_id`,`call_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `idx_glossary_org_normalized` ON `glossary_entries` (`organization_id`,`normalized_term`,`category`);--> statement-breakpoint
CREATE INDEX `idx_processing_org_status_created` ON `processing_events` (`organization_id`,`status`,`created_at`);--> statement-breakpoint
CREATE INDEX `idx_processing_org_call_created` ON `processing_events` (`organization_id`,`call_id`,`created_at`);--> statement-breakpoint
CREATE INDEX `idx_tasks_org_status_due` ON `tasks` (`organization_id`,`status`,`due_at`);--> statement-breakpoint
CREATE INDEX `idx_segments_org_call_position` ON `transcript_segments` (`organization_id`,`call_id`,`position`);