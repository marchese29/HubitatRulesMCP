# RuleEngine Testing Plan

## Overview

This document outlines the comprehensive testing strategy for the `RuleEngine` class, focusing on both unit tests and functional use-case tests. The goal is to ensure the RuleEngine correctly handles condition management, device event processing, timing behavior, and complex dependency scenarios.

## Testing Strategy

### Hybrid Approach
- **Unit Tests**: Fast, isolated tests using mocks for individual method testing
- **Functional Tests**: Use-case driven tests that exercise multiple components together
- **Time-based Tests**: Combination of mock timers (fast) and short real timers (integration confidence)

### Test Categories
1. **Unit Tests** - Individual method behavior, isolated with mocks
2. **Functional Tests** - End-to-end use cases with realistic workflows  
3. **Edge Case Tests** - Error conditions, boundary cases, cleanup verification
4. **Performance Tests** - Concurrency, memory usage, scalability

## Testing Infrastructure

### Required Components
- **MockTimerService**: Controllable timer service for fast time-based testing
- **TestCondition Classes**: Concrete implementations of EngineCondition for testing
- **Event Factories**: Helpers for creating HubitatDeviceEvent objects
- **State Assertion Helpers**: Utilities for verifying internal engine state

---

## Implementation Milestones

## Milestone 1: Testing Infrastructure & Basic Unit Tests

**Goal**: Set up testing infrastructure and implement basic unit tests for core RuleEngine methods.

### Deliverables Checklist
- [x] Create `MockTimerService` class with controllable timer behavior
- [x] Create test condition classes (`SimpleCondition`, `TimeoutCondition`, `DurationCondition`)
- [x] Create helper factories for device events and test data
- [x] Implement unit tests for basic methods:
  - [x] `get_condition_state()` - returns correct boolean values
  - [x] `_remove_condition()` - cleans up internal state properly
  - [x] `_propagate_state_update()` - correctly updates dependent conditions
- [x] Set up test fixtures in conftest.py for RuleEngine testing
- [x] Verify all unit tests run fast (< 100ms total)

### Success Criteria
- All basic unit tests pass
- Test infrastructure supports creating engine instances with mocks
- Timer-related tests run instantly using MockTimerService
- Test coverage for basic engine state management

---

## Milestone 2: Core Functional Use Cases

**Goal**: Implement functional tests for the primary use cases the RuleEngine supports.

### Deliverables Checklist

#### Simple Condition Scenarios
- [ ] Test: Add condition, trigger device event, verify condition fires
- [ ] Test: Multiple independent conditions on different devices
- [ ] Test: Multiple conditions on same device (both should update)
- [ ] Test: Condition state inquiry after various events

#### Condition Lifecycle
- [ ] Test: Add condition with initial device state fetching
- [ ] Test: Remove condition manually (cleanup verification)
- [ ] Test: Condition fires and auto-removes itself
- [ ] Test: Get condition state for active vs removed conditions

#### Device Event Processing  
- [ ] Test: Relevant device events trigger condition evaluation
- [ ] Test: Irrelevant device events are ignored
- [ ] Test: Rapid successive events on same device
- [ ] Test: Events for non-tracked devices don't affect engine

### Success Criteria
- All core use cases pass functional tests
- Device event processing works correctly
- Condition lifecycle management is robust
- Tests complete quickly using mock timer service

---

## Milestone 3: Time-based Behavior Testing

**Goal**: Thoroughly test timeout and duration functionality using hybrid timing approach.

### Deliverables Checklist

#### Timeout Behavior (Mock Timer Tests)
- [ ] Test: Condition with timeout fires timeout event when timer expires
- [ ] Test: Timeout timer is cancelled when condition becomes true
- [ ] Test: Multiple conditions with different timeouts
- [ ] Test: Remove condition cancels its timeout timer

#### Duration Behavior (Mock Timer Tests)  
- [ ] Test: Condition with duration only fires after staying true for full duration
- [ ] Test: Duration timer resets when condition becomes false
- [ ] Test: Duration timer fires when condition stays true long enough
- [ ] Test: Remove condition cancels its duration timer

#### Combined Timeout + Duration
- [ ] Test: Condition with both timeout and duration
- [ ] Test: Timeout fires if condition never becomes true
- [ ] Test: Duration fires if condition stays true long enough
- [ ] Test: Proper timer cleanup in all scenarios

#### Integration Tests (Short Real Timers)
- [ ] Test: End-to-end timeout behavior with real timer (10ms timeout)
- [ ] Test: End-to-end duration behavior with real timer (10ms duration)
- [ ] Test: Timer service integration works correctly

### Success Criteria
- All timeout/duration logic works correctly
- Timer cleanup prevents memory leaks
- Integration tests provide confidence in real timer interaction
- Mock timer tests run instantly, integration tests complete in < 1 second

---

## Milestone 4: Complex Scenarios & Edge Cases

**Goal**: Test complex dependency scenarios, error conditions, and edge cases.

### Deliverables Checklist

#### Condition Dependencies
- [ ] Test: Parent condition depends on single child condition
- [ ] Test: Parent condition depends on multiple child conditions  
- [ ] Test: Multi-level dependency chain (grandparent → parent → child)
- [ ] Test: Child condition state change propagates to parent
- [ ] Test: Remove child condition while parent is active

#### Edge Cases
- [ ] Test: Condition is immediately true when added
- [ ] Test: Condition never becomes true (timeout scenario)
- [ ] Test: Add same condition twice (duplicate handling)
- [ ] Test: Remove condition that doesn't exist
- [ ] Test: Get state of non-existent condition

#### Error Handling & Robustness
- [ ] Test: Device attribute fetching fails during initialization
- [ ] Test: Condition evaluation throws exception
- [ ] Test: Timer service operations fail gracefully
- [ ] Test: Engine handles malformed device events

#### Concurrency & Thread Safety
- [ ] Test: Concurrent add/remove operations don't corrupt state
- [ ] Test: Engine lock protects critical sections properly
- [ ] Test: Rapid event processing maintains consistency

#### Memory & Resource Management
- [ ] Test: Removed conditions don't leak memory
- [ ] Test: Device mappings are properly cleaned up
- [ ] Test: Timer resources are released correctly

### Success Criteria
- All edge cases are handled gracefully
- Complex dependency scenarios work correctly
- No memory leaks or resource leaks
- Engine remains stable under concurrent access

---

## Test Implementation Guidelines

### Unit Test Patterns
```python
def test_method_name_behavior():
    """Test description"""
    # Arrange - set up test data and mocks
    # Act - call the method being tested
    # Assert - verify expected behavior
```

### Functional Test Patterns
```python
async def test_use_case_description():
    """Test realistic workflow using correct API"""
    # Set up engine with mocks
    engine = RuleEngine(mock_he_client, mock_timer_service)
    
    # Create condition with event notification
    condition = SimpleCondition("test_condition", device_id=123)
    condition_event = asyncio.Event()
    timeout_event = asyncio.Event()
    
    # Add condition to engine
    await engine.add_condition(condition, condition_event, timeout_event)
    
    # Trigger device event through public API
    device_event = create_device_event(123, "switch", "on")
    await engine.on_device_event(device_event)
    
    # Verify condition fired by waiting for event
    fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
    assert fired
    
    # Note: Condition auto-removes itself when it fires
    with pytest.raises(KeyError):
        engine.get_condition_state(condition)
```

### Event-based Notification Patterns
```python
# Condition firing notification
condition_event = asyncio.Event()
timeout_event = asyncio.Event()
await engine.add_condition(condition, condition_event, timeout_event)

# Wait for condition to fire
try:
    await asyncio.wait_for(condition_event.wait(), timeout=0.1)
    condition_fired = True
except asyncio.TimeoutError:
    condition_fired = False

# Wait for timeout
try:
    await asyncio.wait_for(timeout_event.wait(), timeout=0.1)
    timeout_occurred = True
except asyncio.TimeoutError:
    timeout_occurred = False
```

### Auto-removal Behavior Testing
```python
# Test auto-removal after condition fires
await engine.add_condition(condition, condition_event)
await engine.on_device_event(trigger_event)

# Wait for condition to fire
await condition_event.wait()

# Condition should now be auto-removed
with pytest.raises(KeyError):
    engine.get_condition_state(condition)
```

### Mock Timer Usage
```python
# Fast unit tests
mock_timer = MockTimerService()
await mock_timer.trigger_timer("timer_id")  # Instant

# Integration tests  
real_timer = TimerService()
condition.timeout = timedelta(milliseconds=10)  # Very short
```

### Test Organization
- `test_rule_engine_unit.py` - Unit tests (Milestone 1)
- `test_rule_engine_functional.py` - Functional tests (Milestone 2) 
- `test_rule_engine_timing.py` - Time-based tests (Milestone 3)
- `test_rule_engine_complex.py` - Complex scenarios (Milestone 4)

## Success Metrics

### Quality Goals
- All tests are deterministic (no flaky tests)
- Tests are maintainable and readable
- Test failures provide clear diagnostic information
- Tests serve as documentation for expected behavior

---

## Next Steps

1. **Start with Milestone 1**: Set up testing infrastructure
2. **Implement incrementally**: Complete each milestone before moving to next
3. **Run tests frequently**: Ensure new tests don't break existing functionality
4. **Review and refactor**: Improve test quality and coverage as needed

This plan provides a systematic approach to thoroughly testing the RuleEngine while maintaining fast test execution and clear progress tracking.
