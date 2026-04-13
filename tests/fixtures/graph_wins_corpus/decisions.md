# Architecture Decision Records

## ADR-017: Migrate from Monolith to Microservices

**Status:** Accepted
**Date:** 2023-06-15
**Decision maker:** Marcus Williams (CTO)
**Implementer:** David Park (Backend Team lead)

### Context
The monolithic Python application could not scale horizontally. Deployment took 45 minutes. A bug in billing affected the entire application.

### Decision
Split into microservices: Authentication, Payment, Order, Notification, Inventory, User Profile. Each team owns their services independently.

### Consequences
- Positive: Independent deployment, team autonomy, technology diversity
- Negative: Distributed tracing complexity, eventual consistency challenges, operational overhead
- Mitigation: Jake Morrison built shared observability stack; Sarah Chen standardized deployment via ArgoCD

## ADR-021: Use PostgreSQL for All Services Instead of Per-Service Databases

**Status:** Accepted
**Date:** 2023-09-20
**Decision maker:** Sarah Chen (Platform Team lead)
**Context:** Running 6 separate database instances was operationally expensive.

### Decision
Consolidate to a single RDS Multi-AZ PostgreSQL cluster with schema-per-service isolation. Services connect via connection pooling (PgBouncer).

### Consequences
- Positive: One backup strategy, one failover process, shared DBA expertise (Jake Morrison)
- Negative: Single point of failure for database. If PostgreSQL goes down, ALL services affected.
- Mitigation: Multi-AZ with automatic failover. Jake Morrison owns the failover runbook (RB-003).
- Risk accepted by: Marcus Williams

## ADR-025: Replace Custom Auth with JWT Tokens

**Status:** Accepted  
**Date:** 2024-01-10
**Decision maker:** David Park
**Implementer:** Lisa Wang

### Context
Session-based authentication required sticky sessions and didn't work with Kubernetes pod scaling.

### Decision
Stateless JWT tokens with 15-minute expiry. Redis cache for token validation to avoid database lookup on every request.

### Consequences
- Positive: Stateless, scales horizontally, no sticky sessions
- Negative: Token revocation requires Redis check (adds latency), cache memory usage (led to INC-2024-102)
- Related: Lisa Wang implemented the Redis cache that later caused the memory leak incident

## ADR-028: Adopt Kong as API Gateway

**Status:** Accepted
**Date:** 2024-02-28
**Decision maker:** David Park
**Implementer:** Maria Santos

### Context
Each service had its own rate limiting and auth middleware. Inconsistent implementations.

### Decision
Centralize via Kong API Gateway. All external traffic routes through Kong for rate limiting, auth validation, and routing.

### Consequences
- Positive: Consistent policies, single point for rate limit management, observability
- Negative: Kong becomes a SPOF for external traffic. Misconfiguration affects all services (INC-2024-089)
- Risk: Maria Santos is sole Kong expert. Bus factor = 1.
