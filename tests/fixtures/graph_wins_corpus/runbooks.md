# Runbooks

## RB-001: Payment Service Unhealthy

### Symptoms
- Payment latency > 500ms
- Error rate > 1%
- Stripe webhook failures

### Diagnosis Steps
1. Check Datadog dashboard: payment-service-overview
2. Verify Authentication Service is healthy (dependency)
3. Check Stripe status page: status.stripe.com
4. Check PostgreSQL connection pool: `SELECT * FROM pg_stat_activity`

### Escalation
- Primary: Ahmed Hassan (Payment Service owner)
- Secondary: David Park (Backend Team lead)
- If database-related: Jake Morrison (DBA responsibilities)

### Known Issues
- Connection pool exhaustion under burst traffic (see INC-2024-089)
- Stripe rate limiting during Black Friday sales events

## RB-002: Authentication Service Degraded

### Symptoms
- Login latency > 2 seconds
- JWT validation failures
- Redis connection errors

### Diagnosis Steps
1. Check memory usage on auth pods (memory leak history, see INC-2024-102)
2. Verify Redis cluster health
3. Check if recent deployment caused regression
4. Review token cache hit rate in Datadog

### Escalation
- Primary: Lisa Wang (Authentication Service owner)
- Secondary: Sarah Chen (Platform Team lead, for infrastructure issues)

### Impact Assessment
- Authentication is upstream of ALL services
- If auth is down: Payment, Orders, User Profiles all fail
- Estimated blast radius: 100% of authenticated traffic

## RB-003: Database Failover

### Symptoms
- Connection timeouts across multiple services
- RDS event notifications
- Increased error rates in Payment, Order, Authentication, Inventory, and User Profile services (all share the PostgreSQL cluster)

### Diagnosis Steps
1. Check AWS RDS console for failover events
2. Verify DNS propagation to new primary
3. Check connection pool recovery across all services
4. Verify replication lag on read replicas

### Escalation
- Primary: Jake Morrison (database infrastructure)
- Secondary: Priya Patel (AWS infrastructure)
- Notify: All service owners (Lisa, Ahmed, David, Tom, Chris)

### Recovery
- Services should auto-reconnect via connection pool
- If pools don't recover: restart pods in order (auth first, then dependent services)
- Restart order matters: Auth → Payment → Order → Notification
