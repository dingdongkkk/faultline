from activity.report import user_report

DAYTIME = [
    "2026-03-01 09:00 | ana | login",
    "2026-03-01 09:10 | ana | click",
    "2026-03-01 09:12 | ana | ping",
    "2026-03-01 11:00 | ana | click",
    "2026-03-01 09:05 | bo | login",
]

NIGHT = [
    "2026-03-01 11:40 PM | ana | login",
    "2026-03-01 11:55 PM | ana | click",
    "2026-03-02 12:10 AM | ana | click",
    "2026-03-02 12:20 AM | ana | logout",
]


def test_daytime_sessions():
    assert user_report(DAYTIME, "ana") == {"sessions": 2, "avg_minutes": 5.0}


def test_other_user_isolated():
    assert user_report(DAYTIME, "bo") == {"sessions": 1, "avg_minutes": 0.0}


def test_session_across_midnight():
    assert user_report(NIGHT, "ana") == {"sessions": 1, "avg_minutes": 40.0}
