def test_scheduler_basic_contract():
    from aetherflow.scheduler.runner import Scheduler

    scheduler = Scheduler()
    result = scheduler.schedule()

    assert isinstance(result, str)
    assert result == "scheduled"
