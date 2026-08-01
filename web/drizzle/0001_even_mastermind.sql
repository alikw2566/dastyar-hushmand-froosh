CREATE TABLE `extraction_evidence` (
	`id` text PRIMARY KEY NOT NULL,
	`organization_id` text NOT NULL,
	`call_id` text NOT NULL,
	`field_name` text NOT NULL,
	`extracted_value` text,
	`confidence` real,
	`source_segment_ids_json` text,
	`exact_quote` text,
	`start_seconds` real,
	`end_seconds` real,
	`extraction_method` text,
	`validation_status` text DEFAULT 'unsupported' NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`call_id`) REFERENCES `calls`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `glossary_entries` (
	`id` text PRIMARY KEY NOT NULL,
	`organization_id` text NOT NULL,
	`term` text NOT NULL,
	`normalized_term` text NOT NULL,
	`category` text NOT NULL,
	`aliases_json` text,
	`active` integer DEFAULT true NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE TABLE `issabel_settings` (
	`organization_id` text PRIMARY KEY NOT NULL,
	`import_mode` text DEFAULT 'disabled' NOT NULL,
	`recordings_path` text,
	`sftp_host` text,
	`sftp_port` integer DEFAULT 22 NOT NULL,
	`sftp_username` text,
	`sftp_remote_path` text,
	`poll_interval` integer DEFAULT 60 NOT NULL,
	`file_stability_seconds` integer DEFAULT 15 NOT NULL,
	`allowed_extensions` text DEFAULT 'wav,mp3,gsm' NOT NULL,
	`quarantine_path` text,
	`filename_pattern` text,
	`enabled` integer DEFAULT false NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
--> statement-breakpoint
CREATE TABLE `processing_events` (
	`id` text PRIMARY KEY NOT NULL,
	`organization_id` text NOT NULL,
	`call_id` text NOT NULL,
	`stage` text NOT NULL,
	`status` text NOT NULL,
	`error_type` text,
	`safe_message` text,
	`stack_trace` text,
	`retry_count` integer DEFAULT 0 NOT NULL,
	`worker` text,
	`correlation_id` text,
	`started_at` text,
	`finished_at` text,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`call_id`) REFERENCES `calls`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
ALTER TABLE `calls` ADD `company_name` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `phone_number` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `city` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `province` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `seller_email` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `product_name` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `product_category` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `sales_stage` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `lead_temperature` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `direction` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `sentiment` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `risk_flags_json` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `followup_required` integer DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE `calls` ADD `followup_at` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `has_manual_correction` integer DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE `calls` ADD `error_type` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `failed_stage` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `retry_count` integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE `calls` ADD `last_retry_at` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `next_retry_at` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `worker` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `correlation_id` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `source_path` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `file_hash` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `detected_at` text;--> statement-breakpoint
ALTER TABLE `calls` ADD `imported_at` text;--> statement-breakpoint
ALTER TABLE `tasks` ADD `company_name` text;--> statement-breakpoint
ALTER TABLE `tasks` ADD `reason` text;--> statement-breakpoint
ALTER TABLE `tasks` ADD `completion_note` text;--> statement-breakpoint
ALTER TABLE `tasks` ADD `completed_at` text;--> statement-breakpoint
ALTER TABLE `tasks` ADD `creation_method` text DEFAULT 'manual' NOT NULL;--> statement-breakpoint
ALTER TABLE `tasks` ADD `evidence_json` text;--> statement-breakpoint
ALTER TABLE `transcript_segments` ADD `speaker_role_confidence` real;--> statement-breakpoint
ALTER TABLE `transcript_segments` ADD `normalized_text` text;--> statement-breakpoint
ALTER TABLE `transcript_segments` ADD `is_manually_corrected` integer DEFAULT false NOT NULL;--> statement-breakpoint
ALTER TABLE `transcript_segments` ADD `correction_user_id` text;--> statement-breakpoint
ALTER TABLE `transcript_segments` ADD `updated_at` text;
