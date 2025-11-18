# Asterisk Queue Setup for Transfer to Queue Tool

This document explains how to configure Asterisk queues to work with the `transfer_to_queue` tool.

## Overview

The `transfer_to_queue` tool transfers callers to ACD (Automatic Call Distribution) queues where they wait for the next available agent. This requires:

1. Queue definitions in `queues.conf`
2. Queue members (agents) configuration
3. Dialplan context for queue handling

## Step 1: Define Queues (`/etc/asterisk/queues.conf`)

Add your queues to the Asterisk queues configuration:

```ini
[sales-queue]
strategy = ringall           ; Ring all available agents
timeout = 15                 ; Ring each agent for 15 seconds
retry = 5                    ; Wait 5 seconds before retrying
maxlen = 10                  ; Maximum queue size
announce-position = yes      ; Announce caller's position
announce-holdtime = yes      ; Announce estimated wait time
musicclass = default         ; Hold music class
joinempty = yes              ; Allow joining even if no agents
leavewhenempty = no          ; Don't kick out when queue becomes empty
ringinuse = no               ; Don't ring agents already on a call

[tech-support-queue]
strategy = leastrecent       ; Ring agent who least recently answered
timeout = 20
retry = 5
maxlen = 15
announce-position = yes
announce-holdtime = yes
musicclass = default
joinempty = yes
leavewhenempty = no
ringinuse = no

[billing-queue]
strategy = random            ; Random agent selection
timeout = 15
retry = 3
maxlen = 5
announce-position = no       ; No position announcements for billing
announce-holdtime = no
musicclass = default
joinempty = yes
leavewhenempty = no
ringinuse = no
```

## Step 2: Configure Queue Members

You can add queue members either statically or dynamically:

### Static Members (in `queues.conf`)

```ini
[sales-queue]
; ... other settings ...
member => PJSIP/agent1
member => PJSIP/agent2
member => PJSIP/agent3

[tech-support-queue]
member => PJSIP/support1
member => PJSIP/support2

[billing-queue]
member => PJSIP/billing1
```

### Dynamic Members (via CLI or dialplan)

Agents can log in/out dynamically:

```bash
# Add member
asterisk -rx "queue add member PJSIP/agent1 to sales-queue"

# Remove member
asterisk -rx "queue remove member PJSIP/agent1 from sales-queue"

# Pause member
asterisk -rx "queue pause member PJSIP/agent1 queue sales-queue reason Break"

# Unpause member
asterisk -rx "queue unpause member PJSIP/agent1 queue sales-queue"
```

## Step 3: Dialplan Configuration (`/etc/asterisk/extensions.conf`)

Create the `agent-queue` context that the AI agent uses:

```ini
[agent-queue]
; This context is called by the AI agent when transferring to a queue
; The AI agent sets the QUEUE_NAME channel variable before continuing here

exten => s,1,NoOp(Queue Transfer from AI Agent)
    same => n,Set(QUEUE=${QUEUE_NAME})
    same => n,NoOp(Transferring to queue: ${QUEUE})
    
    ; Optional: Play message before entering queue
    same => n,Playback(queue-transfer-message)
    
    ; Add caller to queue
    ; Format: Queue(queuename,options,URL,announceoverride,timeout)
    ; Options:
    ;   t = Allow callee to transfer
    ;   T = Allow caller to transfer  
    ;   r = Ring instead of music on hold
    ;   n = No retry if all agents are unavailable
    same => n,Queue(${QUEUE},t,,,300)
    
    ; If queue times out or fails
    same => n,NoOp(Queue result: ${QUEUESTATUS})
    same => n,GotoIf($["${QUEUESTATUS}" = "TIMEOUT"]?timeout)
    same => n,GotoIf($["${QUEUESTATUS}" = "FULL"]?full)
    same => n,GotoIf($["${QUEUESTATUS}" = "JOINEMPTY"]?unavailable)
    same => n,GotoIf($["${QUEUESTATUS}" = "LEAVEEMPTY"]?unavailable)
    same => n,Goto(end)
    
    ; Handle timeout (caller waited too long)
    same => n(timeout),NoOp(Queue timeout)
    same => n,Playback(queue-timeout)
    same => n,Playback(please-try-again-later)
    same => n,Goto(end)
    
    ; Handle full queue
    same => n(full),NoOp(Queue full)
    same => n,Playback(queue-full)
    same => n,Playback(please-try-again-later)
    same => n,Goto(end)
    
    ; Handle no agents available
    same => n(unavailable),NoOp(No agents available)
    same => n,Playback(all-agents-busy)
    same => n,Playback(please-try-again-later)
    same => n,Goto(end)
    
    ; End
    same => n(end),Hangup()
```

## Step 4: Reload Asterisk Configuration

After making changes, reload the configuration:

```bash
# Reload queues
asterisk -rx "queue reload"

# Or reload all config
asterisk -rx "core reload"

# Verify queues are loaded
asterisk -rx "queue show"
```

## Step 5: Verify Queue Status

Check queue status and members:

```bash
# Show all queues
asterisk -rx "queue show"

# Show specific queue
asterisk -rx "queue show sales-queue"

# Show queue members
asterisk -rx "queue show sales-queue members"

# Show queue statistics
asterisk -rx "queue show sales-queue"
```

## Testing the Integration

### Test via CLI

You can test queue functionality directly:

```bash
# Originate a test call to the queue context
asterisk -rx "channel originate PJSIP/testphone application Queue sales-queue"
```

### Test via AI Agent

1. Call your AI voice agent
2. Say: "I need to speak with sales"
3. The AI should invoke `transfer_to_queue` with queue="sales"
4. You should hear hold music and position announcements
5. When an agent answers, the call connects

### Monitor in Real-Time

```bash
# Watch queue activity
asterisk -rx "queue show" 

# Follow logs
tail -f /var/log/asterisk/full
```

## Troubleshooting

### Queue Not Found

**Error**: `Queue 'sales-queue' not found`

**Fix**: 
1. Check `queues.conf` for queue definition
2. Reload: `asterisk -rx "queue reload"`
3. Verify: `asterisk -rx "queue show sales-queue"`

### No Agents Available

**Error**: Caller gets "no agents available" message

**Fix**:
1. Check members: `asterisk -rx "queue show sales-queue members"`
2. Add members: `asterisk -rx "queue add member PJSIP/agent1 to sales-queue"`
3. Verify members aren't paused

### Call Not Entering Queue

**Error**: Call doesn't transfer to queue

**Fix**:
1. Check dialplan: `asterisk -rx "dialplan show agent-queue"`
2. Verify context exists
3. Check AI agent logs for QUEUE_NAME variable
4. Verify ARI permissions

### Queue Timeout

**Error**: Callers wait but never connect

**Fix**:
1. Check if agents are logged in
2. Verify agents aren't busy on other calls
3. Increase timeout in `Queue()` application
4. Check agent devices are registered

## Queue Strategies

Choose appropriate strategy for your use case:

- **ringall**: Ring all available members (best for small teams)
- **leastrecent**: Ring agent who answered least recently (fair distribution)
- **fewestcalls**: Ring agent with fewest completed calls
- **random**: Random agent selection
- **rrmemory**: Round-robin with memory
- **rrordered**: Round-robin ordered by member position
- **linear**: Ring agents in order listed
- **wrandom**: Weighted random based on member penalty

## Advanced Configuration

### Queue Member Priorities

Set priority for certain agents:

```ini
[sales-queue]
member => PJSIP/senior-agent,0    ; Priority 0 (highest)
member => PJSIP/agent1,1          ; Priority 1
member => PJSIP/agent2,1          ; Priority 1
```

### Queue Announcements

Customize announcements:

```ini
[sales-queue]
announce-frequency = 30       ; Announce position every 30 seconds
announce-round-seconds = 10   ; Round to nearest 10 seconds
periodic-announce = queue-periodic-announce
periodic-announce-frequency = 30
```

### Queue Statistics

Enable queue statistics for reporting:

```ini
[general]
persistentmembers = yes
autofill = yes
monitor-type = mixmonitor
```

## Integration with AI Agent Config

The queue names in your AI agent config (`config/ai-agent.yaml`) must match the Asterisk queue names:

```yaml
tools:
  transfer_to_queue:
    enabled: true
    queues:
      sales:
        asterisk_queue: "sales-queue"  # Must match queues.conf
        description: "Sales team"
        max_wait_time: 300
```

## See Also

- Asterisk Queue Documentation: https://wiki.asterisk.org/wiki/display/AST/Queues
- Queue Strategies: https://wiki.asterisk.org/wiki/display/AST/Queue+Strategies
- Queue Applications: https://wiki.asterisk.org/wiki/display/AST/Asterisk+18+Application_Queue
