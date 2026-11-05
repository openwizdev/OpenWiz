# Synthetic notification contract examples

synthetic_assumptions: all ids, source facts, outcomes, times and subscription
bindings below are invented interface examples, never observed transport or
phone delivery. T3–T7 consume the named examples through this fenced JSON map.
README fixtures use the repository scanner's documented prose/example form;
they are not room-cli captures. Schema and strict-reader mutation tests check
every nested object. Production source currentness and transport are unavailable.

```json
{
  "decision": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "source_fact": {
        "decision": {
          "binding": {
            "repository": "synthetic-owner/synthetic-repo",
            "subject": {
              "kind": "issue",
              "number": 901
            },
            "comment_id": 902,
            "request_id": "syn_request_1",
            "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
          },
          "state": "open",
          "current": {
            "known": true
          },
          "risk": "ordinary",
          "coverage": {
            "state": "complete",
            "gaps": []
          },
          "freshness": {
            "state": "fresh",
            "snapshot_at": {
              "known": 1700000000000
            }
          }
        }
      }
    }
  },
  "decision-unknown": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "source_fact": {
        "decision": {
          "binding": {
            "repository": "synthetic-owner/synthetic-repo",
            "subject": {
              "kind": "issue",
              "number": 901
            },
            "comment_id": 902,
            "request_id": "syn_request_1",
            "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
          },
          "state": "open",
          "current": {
            "unknown": "Synthetic independent verification unavailable"
          },
          "risk": "ordinary",
          "coverage": {
            "state": "partial",
            "gaps": [
              {
                "source": "decisions",
                "reason": "Synthetic independent verification unavailable"
              }
            ]
          },
          "freshness": {
            "state": "unknown",
            "snapshot_at": {
              "unknown": "Synthetic verification snapshot unavailable"
            }
          }
        }
      }
    }
  },
  "incident": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "source_fact": {
        "incident": {
          "binding": {
            "repository": "synthetic-owner/synthetic-repo",
            "owner": "syn_engine_1",
            "source": "service_health",
            "subject": "tick",
            "incident": "syn_incident_1"
          },
          "state": "escalated",
          "owner_escalated": {
            "known": true
          },
          "coverage": {
            "state": "complete",
            "gaps": []
          },
          "freshness": {
            "state": "fresh",
            "snapshot_at": {
              "known": 1700000000000
            }
          }
        }
      }
    }
  },
  "event": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "source_fact": {
        "event": {
          "binding": {
            "repository": "synthetic-owner/synthetic-repo",
            "source": "event_router",
            "subject": "syn_pr_903",
            "event_id": "syn_event_1",
            "revision": "syn_head_1"
          },
          "category": "ci_failed",
          "current": {
            "known": true
          },
          "coverage": {
            "state": "complete",
            "gaps": []
          },
          "freshness": {
            "state": "fresh",
            "snapshot_at": {
              "known": 1700000000000
            }
          }
        }
      }
    }
  },
  "preferences": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "preferences": {
        "generation": 0,
        "enabled": false,
        "categories": {
          "decision": true,
          "recovery_escalation": true,
          "ci_failed": false,
          "review_findings": false,
          "re_check": false,
          "merge": false,
          "agent_complete": false,
          "ready_stock_changed": false,
          "loop_missed": false,
          "loop_stuck": false,
          "loop_disabled": false,
          "loop_run_changed": false,
          "recovery_changed": false,
          "service_update": false,
          "contract_changed": false,
          "fleet_wait_changed": false
        }
      }
    }
  },
  "preference-write": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "preference_write": {
        "operation_id": "22222222222222222222222222222222",
        "expected_generation": 0,
        "enabled": true,
        "categories": {
          "decision": true,
          "recovery_escalation": true,
          "ci_failed": false,
          "review_findings": false,
          "re_check": false,
          "merge": false,
          "agent_complete": false,
          "ready_stock_changed": false,
          "loop_missed": false,
          "loop_stuck": false,
          "loop_disabled": false,
          "loop_run_changed": false,
          "recovery_changed": false,
          "service_update": false,
          "contract_changed": false,
          "fleet_wait_changed": false
        }
      }
    }
  },
  "subscription": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "subscription": {
        "generation": 0,
        "state": "absent",
        "binding_id": null,
        "reason": "Synthetic subscription is absent",
        "next": "Synthetic explicit owner enable required"
      }
    }
  },
  "subscription-write": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "subscription_write": {
        "operation_id": "33333333333333333333333333333333",
        "expected_generation": 0,
        "binding_id": "syn_protected_binding_1"
      }
    }
  },
  "capability": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "capability": {
        "state": "unavailable",
        "permission": "unknown",
        "reason": "Synthetic transport is not bound",
        "next": "Synthetic discovery must establish a binding"
      }
    }
  },
  "submission": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "submission": {
        "dispatch_id": "11111111111111111111111111111111",
        "group": {
          "decision": {
            "repository": "synthetic-owner/synthetic-repo",
            "subject": {
              "kind": "issue",
              "number": 901
            },
            "comment_id": 902,
            "request_id": "syn_request_1",
            "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
          }
        },
        "preference_generation": 1,
        "subscription_generation": 1,
        "payload": {
          "title": "OpenWiz needs your attention",
          "target_token": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        }
      }
    }
  },
  "dispatch": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "dispatch": {
        "submission": {
          "dispatch_id": "11111111111111111111111111111111",
          "group": {
            "decision": {
              "repository": "synthetic-owner/synthetic-repo",
              "subject": {
                "kind": "issue",
                "number": 901
              },
              "comment_id": 902,
              "request_id": "syn_request_1",
              "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            }
          },
          "preference_generation": 1,
          "subscription_generation": 1,
          "payload": {
            "title": "OpenWiz needs your attention",
            "target_token": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
          }
        },
        "state": "accepted",
        "group_state": "open",
        "reserved_at": 1700000000000,
        "updated_at": 1700000000001,
        "outcome": {
          "state": "accepted",
          "reason": "Synthetic boundary accepted dispatch; phone observation is unverified"
        }
      }
    }
  },
  "dispatch-reserved": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "dispatch": {
        "submission": {
          "dispatch_id": "11111111111111111111111111111111",
          "group": {
            "decision": {
              "repository": "synthetic-owner/synthetic-repo",
              "subject": {
                "kind": "issue",
                "number": 901
              },
              "comment_id": 902,
              "request_id": "syn_request_1",
              "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            }
          },
          "preference_generation": 1,
          "subscription_generation": 1,
          "payload": {
            "title": "OpenWiz needs your attention",
            "target_token": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
          }
        },
        "state": "reserved",
        "group_state": "open",
        "reserved_at": 1700000000000,
        "updated_at": 1700000000001,
        "outcome": null
      }
    }
  },
  "dispatch-submitting": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "dispatch": {
        "submission": {
          "dispatch_id": "11111111111111111111111111111111",
          "group": {
            "decision": {
              "repository": "synthetic-owner/synthetic-repo",
              "subject": {
                "kind": "issue",
                "number": 901
              },
              "comment_id": 902,
              "request_id": "syn_request_1",
              "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            }
          },
          "preference_generation": 1,
          "subscription_generation": 1,
          "payload": {
            "title": "OpenWiz needs your attention",
            "target_token": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
          }
        },
        "state": "submitting",
        "group_state": "open",
        "reserved_at": 1700000000000,
        "updated_at": 1700000000001,
        "outcome": null
      }
    }
  },
  "dispatch-pending": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "dispatch": {
        "submission": {
          "dispatch_id": "11111111111111111111111111111111",
          "group": {
            "decision": {
              "repository": "synthetic-owner/synthetic-repo",
              "subject": {
                "kind": "issue",
                "number": 901
              },
              "comment_id": 902,
              "request_id": "syn_request_1",
              "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            }
          },
          "preference_generation": 1,
          "subscription_generation": 1,
          "payload": {
            "title": "OpenWiz needs your attention",
            "target_token": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
          }
        },
        "state": "pending",
        "group_state": "open",
        "reserved_at": 1700000000000,
        "updated_at": 1700000000001,
        "outcome": {
          "state": "pending",
          "reason": "Synthetic boundary outcome"
        }
      }
    }
  },
  "dispatch-failed": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "dispatch": {
        "submission": {
          "dispatch_id": "11111111111111111111111111111111",
          "group": {
            "decision": {
              "repository": "synthetic-owner/synthetic-repo",
              "subject": {
                "kind": "issue",
                "number": 901
              },
              "comment_id": 902,
              "request_id": "syn_request_1",
              "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            }
          },
          "preference_generation": 1,
          "subscription_generation": 1,
          "payload": {
            "title": "OpenWiz needs your attention",
            "target_token": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
          }
        },
        "state": "failed",
        "group_state": "open",
        "reserved_at": 1700000000000,
        "updated_at": 1700000000001,
        "outcome": {
          "state": "failed",
          "reason": "Synthetic boundary outcome"
        }
      }
    }
  },
  "dispatch-uncertain": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "dispatch": {
        "submission": {
          "dispatch_id": "11111111111111111111111111111111",
          "group": {
            "decision": {
              "repository": "synthetic-owner/synthetic-repo",
              "subject": {
                "kind": "issue",
                "number": 901
              },
              "comment_id": 902,
              "request_id": "syn_request_1",
              "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            }
          },
          "preference_generation": 1,
          "subscription_generation": 1,
          "payload": {
            "title": "OpenWiz needs your attention",
            "target_token": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
          }
        },
        "state": "uncertain",
        "group_state": "open",
        "reserved_at": 1700000000000,
        "updated_at": 1700000000001,
        "outcome": {
          "state": "uncertain",
          "reason": "Synthetic boundary outcome"
        }
      }
    }
  },
  "dispatch-cancelled": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "dispatch": {
        "submission": {
          "dispatch_id": "11111111111111111111111111111111",
          "group": {
            "decision": {
              "repository": "synthetic-owner/synthetic-repo",
              "subject": {
                "kind": "issue",
                "number": 901
              },
              "comment_id": 902,
              "request_id": "syn_request_1",
              "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            }
          },
          "preference_generation": 1,
          "subscription_generation": 1,
          "payload": {
            "title": "OpenWiz needs your attention",
            "target_token": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
          }
        },
        "state": "cancelled",
        "group_state": "open",
        "reserved_at": 1700000000000,
        "updated_at": 1700000000001,
        "outcome": null
      }
    }
  },
  "outcome-pending": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "delivery_outcome": {
        "state": "pending",
        "reason": "Synthetic boundary outcome; phone observation unverified"
      }
    }
  },
  "outcome-accepted": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "delivery_outcome": {
        "state": "accepted",
        "reason": "Synthetic boundary outcome; phone observation unverified"
      }
    }
  },
  "outcome-failed": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "delivery_outcome": {
        "state": "failed",
        "reason": "Synthetic boundary outcome; phone observation unverified"
      }
    }
  },
  "outcome-uncertain": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "delivery_outcome": {
        "state": "uncertain",
        "reason": "Synthetic boundary outcome; phone observation unverified"
      }
    }
  },
  "status": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "status": {
        "state": "off",
        "reason": "Synthetic delivery disabled",
        "next": "Synthetic explicit owner enable required",
        "preferences": {
          "generation": 0,
          "enabled": false,
          "categories": {
            "decision": true,
            "recovery_escalation": true,
            "ci_failed": false,
            "review_findings": false,
            "re_check": false,
            "merge": false,
            "agent_complete": false,
            "ready_stock_changed": false,
            "loop_missed": false,
            "loop_stuck": false,
            "loop_disabled": false,
            "loop_run_changed": false,
            "recovery_changed": false,
            "service_update": false,
            "contract_changed": false,
            "fleet_wait_changed": false
          }
        },
        "capability": {
          "state": "unavailable",
          "permission": "unknown",
          "reason": "Synthetic transport is not bound",
          "next": "Synthetic discovery must establish a binding"
        },
        "subscription": {
          "generation": 0,
          "state": "absent",
          "binding_id": null,
          "reason": "Synthetic subscription is absent",
          "next": "Synthetic explicit owner enable required"
        },
        "sources": [
          {
            "category": "decision",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "recovery_escalation",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "ci_failed",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "review_findings",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "re_check",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "merge",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "agent_complete",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "ready_stock_changed",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "loop_missed",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "loop_stuck",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "loop_disabled",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "loop_run_changed",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "recovery_changed",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "service_update",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "contract_changed",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          },
          {
            "category": "fleet_wait_changed",
            "available": {
              "unknown": "Synthetic source binding unavailable"
            },
            "reason": "Synthetic source binding unavailable"
          }
        ],
        "latest": null,
        "coverage": {
          "state": "partial",
          "gaps": [
            {
              "source": "decisions",
              "reason": "Synthetic independent currentness unavailable"
            }
          ]
        },
        "freshness": {
          "state": "unknown",
          "snapshot_at": {
            "unknown": "Synthetic no completed source pass"
          }
        }
      }
    }
  },
  "target": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "target_result": {
        "reference": {
          "decision": {
            "repository": "synthetic-owner/synthetic-repo",
            "subject": {
              "kind": "issue",
              "number": 901
            },
            "comment_id": 902,
            "request_id": "syn_request_1",
            "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
          }
        },
        "state": "current",
        "coverage": {
          "state": "complete",
          "gaps": []
        },
        "freshness": {
          "state": "fresh",
          "snapshot_at": {
            "known": 1700000000000
          }
        }
      }
    }
  },
  "stock-fed": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "stock": {
        "coverage": {
          "state": "complete",
          "gaps": []
        },
        "freshness": {
          "state": "fresh",
          "snapshot_at": {
            "known": 1700000000000
          }
        },
        "projects": [
          {
            "project": "prj_syn_0001",
            "coverage": {
              "state": "complete",
              "gaps": []
            },
            "freshness": {
              "state": "fresh",
              "snapshot_at": {
                "known": 1700000000000
              }
            },
            "counts": {
              "known": {
                "ready": 4,
                "running": 2,
                "blocked": 1,
                "held": 2,
                "unapproved": 3,
                "owner_wait": 4,
                "capacity_wait": 5,
                "unknown": 0,
                "state": "fed"
              }
            },
            "last_good": null
          }
        ],
        "totals": {
          "known": {
            "ready": 4,
            "running": 2,
            "blocked": 1,
            "held": 2,
            "unapproved": 3,
            "owner_wait": 4,
            "capacity_wait": 5,
            "unknown": 0,
            "state": "fed"
          }
        }
      }
    }
  },
  "stock-low": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "stock": {
        "coverage": {
          "state": "complete",
          "gaps": []
        },
        "freshness": {
          "state": "fresh",
          "snapshot_at": {
            "known": 1700000000000
          }
        },
        "projects": [
          {
            "project": "prj_syn_0001",
            "coverage": {
              "state": "complete",
              "gaps": []
            },
            "freshness": {
              "state": "fresh",
              "snapshot_at": {
                "known": 1700000000000
              }
            },
            "counts": {
              "known": {
                "ready": 3,
                "running": 2,
                "blocked": 1,
                "held": 2,
                "unapproved": 3,
                "owner_wait": 4,
                "capacity_wait": 5,
                "unknown": 0,
                "state": "low_stock"
              }
            },
            "last_good": null
          }
        ],
        "totals": {
          "known": {
            "ready": 3,
            "running": 2,
            "blocked": 1,
            "held": 2,
            "unapproved": 3,
            "owner_wait": 4,
            "capacity_wait": 5,
            "unknown": 0,
            "state": "low_stock"
          }
        }
      }
    }
  },
  "stock-dry": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "stock": {
        "coverage": {
          "state": "complete",
          "gaps": []
        },
        "freshness": {
          "state": "fresh",
          "snapshot_at": {
            "known": 1700000000000
          }
        },
        "projects": [
          {
            "project": "prj_syn_0001",
            "coverage": {
              "state": "complete",
              "gaps": []
            },
            "freshness": {
              "state": "fresh",
              "snapshot_at": {
                "known": 1700000000000
              }
            },
            "counts": {
              "known": {
                "ready": 0,
                "running": 2,
                "blocked": 1,
                "held": 2,
                "unapproved": 3,
                "owner_wait": 4,
                "capacity_wait": 5,
                "unknown": 0,
                "state": "running_dry"
              }
            },
            "last_good": null
          }
        ],
        "totals": {
          "known": {
            "ready": 0,
            "running": 2,
            "blocked": 1,
            "held": 2,
            "unapproved": 3,
            "owner_wait": 4,
            "capacity_wait": 5,
            "unknown": 0,
            "state": "running_dry"
          }
        }
      }
    }
  },
  "stock-idle": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "stock": {
        "coverage": {
          "state": "complete",
          "gaps": []
        },
        "freshness": {
          "state": "fresh",
          "snapshot_at": {
            "known": 1700000000000
          }
        },
        "projects": [
          {
            "project": "prj_syn_0001",
            "coverage": {
              "state": "complete",
              "gaps": []
            },
            "freshness": {
              "state": "fresh",
              "snapshot_at": {
                "known": 1700000000000
              }
            },
            "counts": {
              "known": {
                "ready": 3,
                "running": 0,
                "blocked": 1,
                "held": 2,
                "unapproved": 3,
                "owner_wait": 4,
                "capacity_wait": 5,
                "unknown": 0,
                "state": "no_builders"
              }
            },
            "last_good": null
          }
        ],
        "totals": {
          "known": {
            "ready": 3,
            "running": 0,
            "blocked": 1,
            "held": 2,
            "unapproved": 3,
            "owner_wait": 4,
            "capacity_wait": 5,
            "unknown": 0,
            "state": "no_builders"
          }
        }
      }
    }
  },
  "stock-empty": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "stock": {
        "coverage": {
          "state": "complete",
          "gaps": []
        },
        "freshness": {
          "state": "fresh",
          "snapshot_at": {
            "known": 1700000000000
          }
        },
        "projects": [
          {
            "project": "prj_syn_0001",
            "coverage": {
              "state": "complete",
              "gaps": []
            },
            "freshness": {
              "state": "fresh",
              "snapshot_at": {
                "known": 1700000000000
              }
            },
            "counts": {
              "known": {
                "ready": 0,
                "running": 0,
                "blocked": 1,
                "held": 2,
                "unapproved": 3,
                "owner_wait": 4,
                "capacity_wait": 5,
                "unknown": 0,
                "state": "running_dry"
              }
            },
            "last_good": null
          }
        ],
        "totals": {
          "known": {
            "ready": 0,
            "running": 0,
            "blocked": 1,
            "held": 2,
            "unapproved": 3,
            "owner_wait": 4,
            "capacity_wait": 5,
            "unknown": 0,
            "state": "running_dry"
          }
        }
      }
    }
  },
  "stock-partial": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "stock": {
        "coverage": {
          "state": "partial",
          "gaps": [
            {
              "source": "plan",
              "reason": "Synthetic configured project source missing"
            }
          ]
        },
        "freshness": {
          "state": "fresh",
          "snapshot_at": {
            "known": 1700000000000
          }
        },
        "projects": [
          {
            "project": "prj_syn_0001",
            "coverage": {
              "state": "complete",
              "gaps": []
            },
            "freshness": {
              "state": "fresh",
              "snapshot_at": {
                "known": 1700000000000
              }
            },
            "counts": {
              "known": {
                "ready": 4,
                "running": 2,
                "blocked": 1,
                "held": 2,
                "unapproved": 3,
                "owner_wait": 4,
                "capacity_wait": 5,
                "unknown": 0,
                "state": "fed"
              }
            },
            "last_good": null
          },
          {
            "project": "prj_syn_0002",
            "coverage": {
              "state": "partial",
              "gaps": [
                {
                  "source": "plan",
                  "reason": "Synthetic configured project source missing"
                }
              ]
            },
            "freshness": {
              "state": "unknown",
              "snapshot_at": {
                "unknown": "Synthetic project unread"
              }
            },
            "counts": {
              "unknown": "Synthetic project unread"
            },
            "last_good": null
          }
        ],
        "totals": {
          "unknown": "Synthetic incomplete or old factory source"
        }
      }
    }
  },
  "stock-stale": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "stock": {
        "coverage": {
          "state": "complete",
          "gaps": []
        },
        "freshness": {
          "state": "stale",
          "snapshot_at": {
            "known": 1699999900000
          }
        },
        "projects": [
          {
            "project": "prj_syn_0001",
            "coverage": {
              "state": "complete",
              "gaps": []
            },
            "freshness": {
              "state": "stale",
              "snapshot_at": {
                "known": 1699999900000
              }
            },
            "counts": {
              "unknown": "Synthetic current count unavailable"
            },
            "last_good": {
              "snapshot_at": 1699999900000,
              "counts": {
                "ready": 4,
                "running": 2,
                "blocked": 1,
                "held": 2,
                "unapproved": 3,
                "owner_wait": 4,
                "capacity_wait": 5,
                "unknown": 0,
                "state": "fed"
              }
            }
          }
        ],
        "totals": {
          "unknown": "Synthetic incomplete or old factory source"
        }
      }
    }
  },
  "stock-unknown": {
    "schema": "openwiz.notifications.v1",
    "record": {
      "stock": {
        "coverage": {
          "state": "partial",
          "gaps": [
            {
              "source": "plan",
              "reason": "Synthetic required source time unavailable"
            }
          ]
        },
        "freshness": {
          "state": "unknown",
          "snapshot_at": {
            "unknown": "Synthetic source time unavailable"
          }
        },
        "projects": [
          {
            "project": "prj_syn_0001",
            "coverage": {
              "state": "partial",
              "gaps": [
                {
                  "source": "plan",
                  "reason": "Synthetic required source time unavailable"
                }
              ]
            },
            "freshness": {
              "state": "unknown",
              "snapshot_at": {
                "unknown": "Synthetic source time unavailable"
              }
            },
            "counts": {
              "unknown": "Synthetic current count unavailable"
            },
            "last_good": {
              "snapshot_at": 1699999900000,
              "counts": {
                "ready": 4,
                "running": 2,
                "blocked": 1,
                "held": 2,
                "unapproved": 3,
                "owner_wait": 4,
                "capacity_wait": 5,
                "unknown": 0,
                "state": "fed"
              }
            }
          }
        ],
        "totals": {
          "unknown": "Synthetic incomplete or old factory source"
        }
      }
    }
  }
}
```
