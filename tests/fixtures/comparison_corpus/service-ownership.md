# Service Ownership

## Authentication Service
The authentication service is owned by Lisa Wang. It is built with Node.js and uses PostgreSQL for user data storage. The service handles login, registration, and JWT token management.

## Payment Processing
Payment processing is owned by Ahmed Hassan. The service is written in Go and integrates with Stripe for credit card transactions. It uses idempotency keys to prevent duplicate charges.

## API Gateway
The API Gateway is maintained by Maria Santos. It uses Kong as the underlying platform and handles rate limiting, request routing, and authentication token validation for all incoming traffic.

## Monitoring Stack
The monitoring infrastructure is owned by Jake Morrison on the Platform Team. It consists of Datadog for metrics and logs, and PagerDuty for alerting. Jake is responsible for the on-call rotation and alert rules.
