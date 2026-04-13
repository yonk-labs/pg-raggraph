# Incident Report: March 15 Payment Outage

## Summary
On March 15, a misconfigured rate limit in Kong caused cascading failures in the payment service, halting all transactions for 47 minutes.

## Timeline
- 14:23 — Kong rate limit rule deployed by Maria Santos as part of routine maintenance
- 14:25 — Payment service begins receiving burst traffic exceeding normal thresholds
- 14:28 — Go service exhausts Stripe connection pool (max 50 connections)
- 14:30 — PagerDuty alerts fire, Jake Morrison acknowledges
- 14:35 — Ahmed Hassan identifies correlation between Kong config change and Stripe errors
- 14:42 — Jake Morrison rolls back Kong configuration to previous version
- 14:45 — Payment service recovers, connection pool drains
- 15:10 — All queued transactions processed, incident closed

## Root Cause
Maria Santos deployed a rate limit change that inadvertently removed the per-client rate cap, allowing unlimited burst traffic to reach the payment service. The Go service had a fixed connection pool of 50 to Stripe, which was overwhelmed.

## Action Items
- Ahmed Hassan: Add circuit breaker between Kong and payment service
- Maria Santos: Implement rate limit change review process with staging validation
- Jake Morrison: Add Stripe connection pool monitoring to Datadog dashboard
