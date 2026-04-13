# Team Communications

## Slack Channel: #platform-team
Jake Morrison posted: "Reminder: Kubernetes cluster upgrade to 1.29 scheduled for next Tuesday. All deployments will be paused for 2 hours starting at 6am UTC."

## Slack Channel: #backend-team  
Ahmed Hassan posted: "The new circuit breaker is deployed. It will trip if payment service error rate exceeds 5% over a 30-second window. When tripped, Kong will return 503 to clients instead of forwarding requests."

Lisa Wang posted: "JWT token cache TTL has been reduced from 1 hour to 15 minutes based on the memory leak incident. Memory usage is now stable at ~200MB per pod."

## Slack Channel: #incidents
David Park posted: "Post-mortem for the March 15 payment outage is scheduled for Thursday at 2pm. All team leads should attend. Ahmed is preparing the analysis."

## Email: From Marcus Williams (CTO) to All Engineering
"Following the March 15 incident, I'm asking all team leads to review their service dependencies and ensure circuit breakers are in place for all external API calls. Sarah Chen will coordinate the review across teams."
