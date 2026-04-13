# Recent Incidents

## INC-2024-089: Payment Service Outage (2024-03-15)

**Severity:** P1
**Duration:** 47 minutes
**Impact:** All payment processing halted, affecting approximately 12,000 transactions.

**Root Cause:** A misconfigured rate limit in the API Gateway (Kong) caused the payment service to receive bursts of duplicate requests. The payment service (written in Go) exhausted its connection pool to Stripe, causing cascading failures.

**Resolution:** Ahmed Hassan identified the issue by correlating Kong logs with Stripe API errors. Jake Morrison rolled back the Kong configuration to the previous version. Priya Patel added a circuit breaker between Kong and the payment service to prevent future cascading failures.

**Action Items:**
- Ahmed Hassan to implement idempotency keys for all payment requests
- Jake Morrison to add connection pool monitoring to Datadog
- David Park to review rate limit configurations across all services

## INC-2024-102: Authentication Service Memory Leak (2024-04-22)

**Severity:** P2
**Duration:** 3 hours (gradual degradation)
**Impact:** Login latency increased from 200ms to 8 seconds, affecting approximately 5,000 users.

**Root Cause:** Lisa Wang's recent JWT token caching implementation had a memory leak in the Node.js authentication service. Tokens were being cached but never evicted, causing the service to consume all available memory on the pod.

**Resolution:** Lisa Wang deployed a hotfix implementing LRU cache eviction with a 15-minute TTL. Tom Nguyen added memory usage alerts to the Kubernetes pod monitoring.

**Action Items:**
- Lisa Wang to add load testing for the token cache
- Tom Nguyen to implement automatic pod restart on OOM threshold
- Sarah Chen to mandate memory profiling for all caching changes

## INC-2024-115: CDN Cache Poisoning (2024-05-10)

**Severity:** P2
**Duration:** 2 hours
**Impact:** Approximately 30% of users saw stale content including outdated pricing pages.

**Root Cause:** Chris Taylor's deployment of a new React build changed the asset hashing strategy without updating the CloudFront cache invalidation rules. Old cached assets referenced new API endpoints that didn't exist yet.

**Resolution:** Alex Johnson manually invalidated the CloudFront cache. Rachel Kim implemented a deployment checklist requiring cache invalidation verification before marking deployments as complete.

**Action Items:**
- Chris Taylor to add cache invalidation to the CI/CD pipeline
- Rachel Kim to create pre-deployment verification in ArgoCD
- Sofia Rodriguez to verify mobile app asset caching behaves correctly
