# Service Dependencies

## Authentication Service
- **Runtime dependencies:** PostgreSQL 15, Redis 7, Node.js 20
- **Upstream services:** None (leaf service)
- **Downstream dependents:** API Gateway, Payment Service, User Profile Service
- **Owner:** Lisa Wang
- **On-call:** Backend Team rotation

## Payment Service
- **Runtime dependencies:** PostgreSQL 15, Stripe API
- **Upstream services:** Authentication Service (validates tokens)
- **Downstream dependents:** Order Service, Subscription Service
- **Owner:** Ahmed Hassan
- **SLA:** 99.99% uptime, <200ms p95 latency

## Order Service
- **Runtime dependencies:** PostgreSQL 15, RabbitMQ
- **Upstream services:** Payment Service, Inventory Service
- **Downstream dependents:** Notification Service, Analytics Pipeline
- **Owner:** David Park
- **Note:** Shares PostgreSQL instance with Payment Service

## Notification Service
- **Runtime dependencies:** SendGrid API, Twilio API
- **Upstream services:** Order Service, User Profile Service
- **Downstream dependents:** None (leaf service)
- **Owner:** Sofia Rodriguez
- **Note:** If SendGrid is down, falls back to Twilio for SMS

## Inventory Service
- **Runtime dependencies:** PostgreSQL 15, Redis 7
- **Upstream services:** None (reads from warehouse API nightly)
- **Downstream dependents:** Order Service, Analytics Pipeline
- **Owner:** Tom Nguyen
- **Note:** Stale data acceptable up to 1 hour

## User Profile Service
- **Runtime dependencies:** PostgreSQL 15, S3 (avatar storage)
- **Upstream services:** Authentication Service
- **Downstream dependents:** Notification Service, Frontend
- **Owner:** Chris Taylor
