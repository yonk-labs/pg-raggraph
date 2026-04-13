# New Engineer Onboarding

## Week 1: Environment Setup

### Prerequisites
- Request AWS access from Priya Patel (Platform Team)
- Get Kubernetes credentials from Jake Morrison
- Request Datadog access from the Platform Team
- Set up VPN access through IT (separate from engineering)

### Development Environment
1. Clone the monorepo from GitHub
2. Install Docker Desktop and kubectl
3. Run `make setup` to configure local development
4. Connect to the staging Kubernetes cluster
5. Verify you can access the internal developer portal (built by Tom Nguyen)

### Access Checklist
- [ ] GitHub org membership
- [ ] AWS IAM role (request via Priya Patel)
- [ ] Kubernetes cluster access (request via Jake Morrison)
- [ ] Datadog account
- [ ] PagerDuty account (if on-call eligible)
- [ ] Stripe test environment (if Backend Team)
- [ ] App Store Connect (if Frontend/Mobile)

## Week 2: Architecture Overview

Meet with your team lead for an architecture walkthrough:
- Platform Team → Sarah Chen
- Backend Team → David Park
- Frontend Team → Rachel Kim

### Required Reading
- This architecture document
- The incident response runbook
- Your team's service documentation in Backstage

## Week 3: First Contribution

### For Backend Engineers
- Pick a ticket from the Backend Team backlog
- David Park or Lisa Wang will pair with you on your first PR
- All PRs require approval from the service owner

### For Frontend Engineers
- Start with a design system component update
- Chris Taylor will walk you through the React migration status
- Alex Johnson owns the design system review process

### For Platform Engineers
- Shadow Jake Morrison on an on-call shift
- Review the Terraform modules with Priya Patel
- Tom Nguyen will onboard you to the developer portal codebase

## On-Call

### Rotation
- Platform Team: 1-week rotations (Jake Morrison, Priya Patel, Tom Nguyen)
- Backend Team: 1-week rotations (all backend engineers)
- Frontend Team: not on-call (issues escalated to Backend or Platform)

### Escalation Path
1. On-call engineer receives PagerDuty alert
2. If not resolved in 15 minutes, escalate to team lead
3. If P1, team lead escalates to CTO Marcus Williams
4. Post-incident review led by Sarah Chen within 48 hours
