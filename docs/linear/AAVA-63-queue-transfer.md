# AAVA-63: Transfer to Queue Tool

**Status**: Ready for Development  
**Priority**: P0 - Critical  
**Complexity**: ⭐ Easy (2/10)  
**Estimated Time**: 2-3 days  
**Assignee**: TBD

---

## Overview

Implement ACD (Automatic Call Distribution) queue transfer tool that allows AI agents to transfer callers to Asterisk queues for agent pickup, enabling proper call center workflows.

---

## Implementation Checklist

### Day 1: Core Implementation
- [ ] Create `src/tools/telephony/queue_transfer.py`
- [ ] Implement queue resolution logic
- [ ] Add configuration schema
- [ ] Implement ARI queue operations

### Day 2: Integration & Testing
- [ ] Add session state management
- [ ] Write 20 unit tests
- [ ] Create test fixtures
- [ ] Test error scenarios

### Day 3: Documentation & Polish
- [ ] Write setup documentation
- [ ] Add config examples
- [ ] Create Asterisk dialplan examples
- [ ] Final testing and refinement

---

## Code Structure

```
src/tools/telephony/queue_transfer.py
├── TransferToQueueTool (class)
│   ├── definition (property)
│   ├── execute (async method)
│   ├── _resolve_queue (method)
│   ├── _get_queue_status (async method)
│   └── _format_wait_message (method)
```

---

## Configuration Example

```yaml
tools:
  transfer_to_queue:
    enabled: true
    queues:
      sales:
        asterisk_queue: "sales-queue"
        description: "Sales team"
        max_wait_time: 300
        announce_position: true
      support:
        asterisk_queue: "tech-support-queue"
        description: "Technical support"
        max_wait_time: 600
        announce_position: true
```

---

## API References

- Asterisk ARI Queue Operations: https://wiki.asterisk.org/wiki/display/AST/Asterisk+18+Queues+REST+API
- Channel Variables: https://wiki.asterisk.org/wiki/display/AST/Asterisk+18+Channels+REST+API#Asterisk18ChannelsRESTAPI-setChannelVar
- Continue in Dialplan: https://wiki.asterisk.org/wiki/display/AST/Asterisk+18+Channels+REST+API#Asterisk18ChannelsRESTAPI-continueInDialplan

---

## Testing Requirements

**Unit Tests** (20 total):
- Queue name resolution (valid, invalid, case insensitive)
- ARI operation calls (verify correct parameters)
- Session state updates
- Error handling (queue not found, queue full)
- Config parsing and validation
- Return message formatting

---

## Success Criteria

- ✅ Queue transfer completes successfully
- ✅ Caller hears position in queue
- ✅ Session state updated correctly
- ✅ Error messages clear and actionable
- ✅ All tests passing
- ✅ Documentation complete
