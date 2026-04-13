# Engineering Team Structure

## Platform Team

The Platform Team is led by Sarah Chen, who reports directly to CTO Marcus Williams. The team is responsible for infrastructure, CI/CD pipelines, and developer tooling.

### Members
- Sarah Chen (Team Lead) — 8 years at the company, previously at Google Cloud
- Jake Morrison (Senior SRE) — owns the Kubernetes cluster and monitoring stack
- Priya Patel (DevOps Engineer) — manages Terraform configs and AWS infrastructure
- Tom Nguyen (Platform Engineer) — built the internal developer portal

### Key Systems
The Platform Team maintains:
- The Kubernetes cluster running on AWS EKS
- ArgoCD for GitOps deployments
- Datadog for monitoring and alerting
- The internal developer portal built with Backstage

## Backend Team

The Backend Team is led by David Park and builds the core API services. They own the authentication system, payment processing, and the main REST API.

### Members
- David Park (Team Lead) — architect of the microservices migration
- Lisa Wang (Senior Backend Engineer) — owns the authentication service
- Ahmed Hassan (Backend Engineer) — payment processing specialist
- Maria Santos (Backend Engineer) — API gateway and rate limiting

### Key Systems
- Authentication service (Node.js, PostgreSQL)
- Payment service (Go, Stripe integration)
- API Gateway (Kong)
- Main REST API (Python, FastAPI)

## Frontend Team

The Frontend Team is led by Rachel Kim and builds the web and mobile applications.

### Members
- Rachel Kim (Team Lead)
- Chris Taylor (Senior Frontend Engineer) — leads the React migration
- Sofia Rodriguez (Mobile Engineer) — iOS and Android apps
- Alex Johnson (Frontend Engineer) — design system maintainer

### Key Systems
- Web application (React, TypeScript)
- Mobile apps (React Native)
- Design system (Storybook)
- CDN and static asset pipeline (CloudFront)
