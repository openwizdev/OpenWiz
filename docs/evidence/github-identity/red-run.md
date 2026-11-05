# GI7 red run: skills/launch-fleet/scripts/test-loop.sh before the loop.sh change

Base: 8d681e3d0cecdca4ce2a366d71b7ba2a04fa7fe5. Command: `sh -x skills/launch-fleet/scripts/test-loop.sh` (exit 1), the trace's last lines, temporary folder shown as $work. Every value is synthetic.

```text
ok   bundled loop runs the packaged fleet and revision in a plain consumer
ok   later runs refresh the consumer while keeping the packaged helpers
exit 1
+ OPENWIZ_GITHUB_APP_KEY=c3ludGhldGlj identity synthetic-app-token-2549 
+ grep -vx synthetic-app-token-2549 $work/gh-token.log
+ [ -z none
none
```

It fails at the claim: with the key secret set, the gh calls get no token (`none`), because loop.sh mints none.
