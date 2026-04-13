# System Architecture

## Overview

Our platform is a microservices architecture running on AWS EKS (Kubernetes). Services communicate via REST APIs and async message queues (Amazon SQS). Data is stored in PostgreSQL (RDS), Redis (ElastiCache), and S3.

## Service Map

### API Gateway (Kong)
- Entry point for all external traffic
- Handles rate limiting, authentication token validation, and request routing
- Maintained by Maria Santos (Backend Team)
- Deployed via Helm charts managed by Jake Morrison

### Authentication Service
- Node.js application with PostgreSQL database
- Handles user registration, login, JWT token issuance, and session management
- Owned by Lisa Wang (Backend Team)
- Uses Redis for token caching (added 2024-04)
- Connects to: PostgreSQL (user data), Redis (cache), SQS (audit events)

### Payment Service
- Go application integrating with Stripe
- Handles payment processing, subscriptions, and refunds
- Owned by Ahmed Hassan (Backend Team)
- Uses idempotency keys to prevent duplicate charges
- Connects to: Stripe API, PostgreSQL (transaction records), SQS (payment events)

### Main REST API
- Python FastAPI application
- Serves the core business logic and data access layer
- Connects to: PostgreSQL (main database), Redis (caching), S3 (file storage)
- Maintained by the Backend Team under David Park

### Web Application
- React + TypeScript SPA
- Served via CloudFront CDN
- Communicates with the API Gateway for all backend interactions
- Maintained by Chris Taylor and Alex Johnson (Frontend Team)

### Mobile Applications
- React Native apps for iOS and Android
- Published to App Store and Google Play
- Maintained by Sofia Rodriguez (Frontend Team)
- Uses the same API Gateway endpoints as the web app

## Infrastructure

### Kubernetes (EKS)
- 3 node groups: general (t3.large), compute (c5.2xlarge), memory (r5.xlarge)
- Managed by Jake Morrison with Terraform
- GitOps deployments via ArgoCD

### Databases
- PostgreSQL 15 on RDS (Multi-AZ) — primary data store
- Redis 7 on ElastiCache — caching and session storage
- S3 — file storage, backups, static assets

### Monitoring
- Datadog for metrics, logs, and APM
- PagerDuty for alerting and on-call rotation
- The Platform Team (Jake Morrison) owns the monitoring stack
