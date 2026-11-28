# Choose CI for your project

Continuous integration (CI) is an opt-in choice for your own project. OpenWiz
leaves the provider selection up to you, and you can skip CI.

Look for the `ci` category in the public
[WizMarket repository](https://github.com/openwizdev/WizMarket). When a CI
listing is available, read its setup instructions and cost information before
choosing it. Check the provider's documentation for current pricing and any
requirements for enabling it in your repository.

## Factory CI routing

The OpenWiz factory's routing policy applies to Linux jobs in its own
repositories. Normally, public repositories use GitHub-hosted runners and
private repositories use Jog. If GitHub Actions hits a limit, public Linux
jobs are routed to Jog until capacity returns. Your project's CI choice is
independent of the factory's routing policy.
