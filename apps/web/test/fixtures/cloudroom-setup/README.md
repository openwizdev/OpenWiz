# CloudRoom setup page fixtures (#2201)

Synthetic install records, in the exact shape `tools/install/cloudroom/cloudroom.py`
saves as `<state>/cloudroom/install.json` (`openwiz.cloudroom-install.v1`). Each
names the synthetic `gui-v9001` installer from `tools/install/cloudroom/fixtures/`;
the operation ids are invented. The page test plants one, runs the real setup
check, and reads the page. Nothing here was downloaded or installed.
