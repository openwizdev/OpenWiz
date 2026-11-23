unset GH_TOKEN GITHUB_TOKEN OPENWIZ_GITHUB_APP_KEY ANTHROPIC_API_KEY OPENAI_API_KEY
export HOME=$HOME
export PATH=$FX/bin:$FX/drivers/hermes/fixtures/bin:$FX/drivers/factory/fixtures/bin:$FX/drivers/pane/fixtures/bin:$STUBS:$HOME/.local/bin:/usr/bin:/bin
export CONDUCTOR_API_KEY=dummy-conductor-value FAKE_CONDUCTOR_KEY=dummy-conductor-value
export CURSOR_API_KEY=dummy-cursor-value FACTORY_API_KEY=dummy-factory-value
export KIT_TRACKER=$FX/tracker.json HEADS_KIT_REPO=example/site HEADS_KIT_TICKET=7
export HEADS_COMMENTS=$FX/comments.json HEADS_GH_LOG=$FX/state/gh-calls.jsonl HEADS_GH_STATE=$FX/state HEADS_GH_LOGIN=example-person
export FAKE_CONDUCTOR_STATE=$FX/state/conductor.json FAKE_CONDUCTOR_LOG=$FX/state/conductor-calls
export FAKE_CURSOR_STATE=$FX/state/cursor.json FAKE_CURSOR_LOG=$FX/state/cursor-calls FAKE_TURNS=$FX/state/turns FAKE_HOLD=$FX/state/hold
export FAKE_FACTORY_HOME=$FX/state/factory FAKE_PANE_STATE=$FX/state/pane.json FAKE_PANE_CALLS=$FX/state/pane-calls
export OPENWIZ_HERMES_STATE=$FX/state/run-hermes OPENWIZ_CONDUCTOR_STATE=$FX/state/run-conductor OPENWIZ_CURSOR_STATE=$FX/state/run-cursor
export OPENWIZ_FACTORY_STATE=$FX/state/run-factory OPENWIZ_PANE_STATE=$FX/state/run-pane
