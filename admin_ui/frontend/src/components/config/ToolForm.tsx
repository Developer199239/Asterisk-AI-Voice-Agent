import React, { useEffect, useState } from 'react';
import { Plus, Trash2, Settings } from 'lucide-react';
import { FormInput, FormSwitch, FormSelect, FormLabel } from '../ui/FormComponents';
import { Modal } from '../ui/Modal';

interface ToolFormProps {
    config: any;
    onChange: (newConfig: any) => void;
}

const DEFAULT_ATTENDED_ANNOUNCEMENT_TEMPLATE =
    "Hi, this is Ava. I'm transferring {caller_display} regarding {context_name}.";
const DEFAULT_ATTENDED_AGENT_DTMF_PROMPT_TEMPLATE =
    "Press 1 to accept this transfer, or 2 to decline.";
const DEFAULT_ATTENDED_CALLER_CONNECTED_PROMPT = "Connecting you now.";
const DEFAULT_ATTENDED_CALLER_DECLINED_PROMPT =
    "I’m not able to complete that transfer right now. Would you like me to take a message, or is there anything else I can help with?";
const DEFAULT_HANGUP_POLICY_MODE = 'normal';
const DEFAULT_HANGUP_END_CALL_MARKERS = [
    "no transcript",
    "no transcript needed",
    "don't send a transcript",
    "do not send a transcript",
    "no need for a transcript",
    "no thanks",
    "no thank you",
    "that's all",
    "that is all",
    "that's it",
    "that is it",
    "nothing else",
    "all set",
    "all good",
    "end the call",
    "end call",
    "hang up",
    "hangup",
    "goodbye",
    "bye",
];
const DEFAULT_HANGUP_ASSISTANT_FAREWELL_MARKERS = [
    "goodbye",
    "bye",
    "thank you for calling",
    "thanks for calling",
    "have a great day",
    "have a good day",
    "take care",
    "ending the call",
    "i'll let you go",
];
const DEFAULT_HANGUP_AFFIRMATIVE_MARKERS = [
    "yes",
    "yeah",
    "yep",
    "correct",
    "that's correct",
    "thats correct",
    "that's right",
    "thats right",
    "right",
    "exactly",
    "affirmative",
];
const DEFAULT_HANGUP_NEGATIVE_MARKERS = [
    "no",
    "nope",
    "nah",
    "negative",
    "don't",
    "dont",
    "do not",
    "not",
    "not needed",
    "no need",
    "no thanks",
    "no thank you",
    "decline",
    "skip",
];

const ToolForm = ({ config, onChange }: ToolFormProps) => {
	    const [editingDestination, setEditingDestination] = useState<string | null>(null);
	    const [destinationForm, setDestinationForm] = useState<any>({});
	    const [hangupMarkerDraft, setHangupMarkerDraft] = useState({
	        end_call: '',
	        assistant_farewell: '',
	        affirmative: '',
	        negative: '',
	    });
	    const [hangupMarkerDirty, setHangupMarkerDirty] = useState({
	        end_call: false,
	        assistant_farewell: false,
	        affirmative: false,
	        negative: false,
	    });

    const updateConfig = (field: string, value: any) => {
        onChange({ ...config, [field]: value });
    };

    const updateNestedConfig = (section: string, field: string, value: any) => {
        onChange({
            ...config,
            [section]: {
                ...config[section],
                [field]: value
            }
        });
    };

    const updateHangupPolicy = (field: string, value: any) => {
        const current = config.hangup_call?.policy || {};
        updateNestedConfig('hangup_call', 'policy', { ...current, [field]: value });
    };

    const updateHangupMarkers = (field: string, value: string[]) => {
        const current = config.hangup_call?.policy || {};
        const markers = { ...(current.markers || {}), [field]: value };
        updateNestedConfig('hangup_call', 'policy', { ...current, markers });
    };

	    const parseMarkerList = (value: string) =>
	        (value || '')
	            .split('\n')
	            .map((line) => line.trim())
	            .filter((line) => line.length > 0);

	    const renderMarkerList = (value: string[] | undefined, fallback: string[]) =>
	        (Array.isArray(value) && value.length > 0 ? value : fallback).join('\n');

	    const endCallMarkerText = renderMarkerList(
	        config.hangup_call?.policy?.markers?.end_call,
	        DEFAULT_HANGUP_END_CALL_MARKERS
	    );
	    const assistantFarewellMarkerText = renderMarkerList(
	        config.hangup_call?.policy?.markers?.assistant_farewell,
	        DEFAULT_HANGUP_ASSISTANT_FAREWELL_MARKERS
	    );
	    const affirmativeMarkerText = renderMarkerList(
	        config.hangup_call?.policy?.markers?.affirmative,
	        DEFAULT_HANGUP_AFFIRMATIVE_MARKERS
	    );
	    const negativeMarkerText = renderMarkerList(
	        config.hangup_call?.policy?.markers?.negative,
	        DEFAULT_HANGUP_NEGATIVE_MARKERS
	    );

	    useEffect(() => {
	        setHangupMarkerDraft((prev) => {
	            let changed = false;
	            const next = { ...prev };

	            if (!hangupMarkerDirty.end_call && prev.end_call !== endCallMarkerText) {
	                next.end_call = endCallMarkerText;
	                changed = true;
	            }
	            if (!hangupMarkerDirty.assistant_farewell && prev.assistant_farewell !== assistantFarewellMarkerText) {
	                next.assistant_farewell = assistantFarewellMarkerText;
	                changed = true;
	            }
	            if (!hangupMarkerDirty.affirmative && prev.affirmative !== affirmativeMarkerText) {
	                next.affirmative = affirmativeMarkerText;
	                changed = true;
	            }
	            if (!hangupMarkerDirty.negative && prev.negative !== negativeMarkerText) {
	                next.negative = negativeMarkerText;
	                changed = true;
	            }

	            return changed ? next : prev;
	        });
	    }, [
	        hangupMarkerDirty.end_call,
	        hangupMarkerDirty.assistant_farewell,
	        hangupMarkerDirty.affirmative,
	        hangupMarkerDirty.negative,
	        endCallMarkerText,
	        assistantFarewellMarkerText,
	        affirmativeMarkerText,
	        negativeMarkerText,
	    ]);

    const handleAttendedTransferToggle = (enabled: boolean) => {
        const existing = config.attended_transfer || {};
        const next: any = { ...existing, enabled };
        if (enabled) {
            // Populate sensible defaults out of the box (user can override).
            if (next.moh_class == null) next.moh_class = 'default';
            if (next.dial_timeout_seconds == null) next.dial_timeout_seconds = 30;
            if (next.accept_timeout_seconds == null) next.accept_timeout_seconds = 15;
            if (next.tts_timeout_seconds == null) next.tts_timeout_seconds = 8;
            if (next.accept_digit == null) next.accept_digit = '1';
            if (next.decline_digit == null) next.decline_digit = '2';
            if (next.announcement_template == null) next.announcement_template = DEFAULT_ATTENDED_ANNOUNCEMENT_TEMPLATE;
            if (next.agent_accept_prompt_template == null) next.agent_accept_prompt_template = DEFAULT_ATTENDED_AGENT_DTMF_PROMPT_TEMPLATE;
            if (next.caller_connected_prompt == null) next.caller_connected_prompt = DEFAULT_ATTENDED_CALLER_CONNECTED_PROMPT;
            if (next.caller_declined_prompt == null) next.caller_declined_prompt = DEFAULT_ATTENDED_CALLER_DECLINED_PROMPT;
        }
        onChange({ ...config, attended_transfer: next });
    };

    // Transfer Destinations Management
    const handleEditDestination = (key: string, data: any) => {
        setEditingDestination(key);
        setDestinationForm({ key, ...data });
    };

    const handleAddDestination = () => {
        setEditingDestination('new_destination');
        setDestinationForm({ key: '', type: 'extension', target: '', description: '', attended_allowed: false });
    };

    const handleSaveDestination = () => {
        if (!destinationForm.key) return;

        const destinations = { ...(config.transfer?.destinations || {}) };

        // If renaming, delete old key
        if (editingDestination !== 'new_destination' && editingDestination !== destinationForm.key) {
            delete destinations[editingDestination!];
        }

        const { key, ...data } = destinationForm;
        destinations[key] = data;

        updateNestedConfig('transfer', 'destinations', destinations);
        setEditingDestination(null);
    };

    const handleDeleteDestination = (key: string) => {
        const destinations = { ...(config.transfer?.destinations || {}) };
        delete destinations[key];
        updateNestedConfig('transfer', 'destinations', destinations);
    };

    const renameInternalExtensionKey = (fromKey: string, toKeyRaw: string) => {
        const toKey = (toKeyRaw || '').trim();
        if (!toKey) {
            alert('Extension key cannot be empty.');
            return;
        }
        if (toKey === fromKey) return;

        const existing = { ...(config.extensions?.internal || {}) };
        if (Object.prototype.hasOwnProperty.call(existing, toKey)) {
            alert(`An extension with key '${toKey}' already exists.`);
            return;
        }

        const renamed: Record<string, any> = {};
        Object.entries(existing).forEach(([k, v]) => {
            if (k === fromKey) renamed[toKey] = v;
            else renamed[k] = v;
        });
        updateNestedConfig('extensions', 'internal', renamed);
    };

    return (
        <div className="space-y-8">
            {/* AI Identity & General Settings */}
            <div className="space-y-4 border-b border-border pb-6">
                <h3 className="text-lg font-semibold text-primary">General Settings</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <FormInput
                        label="Agent Name"
                        value={config.ai_identity?.name || 'AI Agent'}
                        onChange={(e) => updateNestedConfig('ai_identity', 'name', e.target.value)}
                        tooltip="The name displayed on the caller's phone during transfers."
                    />
                    <FormInput
                        label="Agent Number"
                        value={config.ai_identity?.number || '6789'}
                        onChange={(e) => updateNestedConfig('ai_identity', 'number', e.target.value)}
                        tooltip="The virtual extension number used by the AI agent."
                    />
                    <FormInput
                        label="Default Action Timeout (s)"
                        type="number"
                        value={config.default_action_timeout || 30}
                        onChange={(e) => updateConfig('default_action_timeout', parseInt(e.target.value))}
                        tooltip="Time to wait for tool execution before timing out."
                    />
                </div>
            </div>

            {/* Telephony Tools */}
            <div className="space-y-6">
                <h3 className="text-lg font-semibold text-primary">Telephony Tools</h3>

                {/* Transfer Tool */}
                <div className="border border-border rounded-lg p-4 bg-card/50">
                    <div className="flex justify-between items-center mb-4">
                        <FormSwitch
                            label="Transfer Tool"
                            description="Allow transferring calls to extensions, queues, or ring groups."
                            checked={config.transfer?.enabled ?? true}
                            onChange={(e) => updateNestedConfig('transfer', 'enabled', e.target.checked)}
                            className="mb-0 border-0 p-0 bg-transparent"
                        />
                    </div>

                    {config.transfer?.enabled !== false && (
                        <div className="mt-4 space-y-4">
                            <FormInput
                                label="Channel Technology"
                                value={config.transfer?.technology || 'SIP'}
                                onChange={(e) => updateNestedConfig('transfer', 'technology', e.target.value)}
                                tooltip="Channel technology for extension transfers (SIP, PJSIP, IAX2, etc.). Default: SIP"
                                placeholder="SIP"
                            />
                            <div className="flex justify-between items-center">
                                <FormLabel>Destinations</FormLabel>
                                <button
                                    onClick={handleAddDestination}
                                    className="text-xs flex items-center bg-secondary px-2 py-1 rounded hover:bg-secondary/80 transition-colors"
                                >
                                    <Plus className="w-3 h-3 mr-1" /> Add Destination
                                </button>
                            </div>

                            <div className="grid grid-cols-1 gap-2">
                                {Object.entries(config.transfer?.destinations || {}).map(([key, dest]: [string, any]) => (
                                    <div key={key} className="flex items-center justify-between p-3 bg-accent/30 rounded border border-border/50">
                                        <div>
                                            <div className="font-medium text-sm">{key}</div>
                                            <div className="text-xs text-muted-foreground">
                                                {dest.type} • {dest.target} • {dest.description}
                                                {dest.type === 'extension' && dest.attended_allowed ? ' • attended' : ''}
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-1">
                                            <button onClick={() => handleEditDestination(key, dest)} className="p-1.5 hover:bg-background rounded text-muted-foreground hover:text-foreground">
                                                <Settings className="w-4 h-4" />
                                            </button>
                                            <button onClick={() => handleDeleteDestination(key)} className="p-1.5 hover:bg-destructive/10 rounded text-destructive">
                                                <Trash2 className="w-4 h-4" />
                                            </button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                {/* Attended (Warm) Transfer */}
                <div className="border border-border rounded-lg p-4 bg-card/50">
                    <FormSwitch
                        label="Attended Transfer (Warm)"
                        description="Warm transfer with MOH, one-way announcement to the agent, and DTMF accept/decline. Requires Local AI Server for TTS."
                        checked={config.attended_transfer?.enabled ?? false}
                        onChange={(e) => handleAttendedTransferToggle(e.target.checked)}
                        className="mb-0 border-0 p-0 bg-transparent"
                    />
                    {config.attended_transfer?.enabled && (
                        <div className="mt-4 pl-4 border-l-2 border-border ml-2 space-y-4">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <FormInput
                                    label="MOH Class"
                                    value={config.attended_transfer?.moh_class || 'default'}
                                    onChange={(e) => updateNestedConfig('attended_transfer', 'moh_class', e.target.value)}
                                    tooltip="Asterisk Music On Hold class used while the destination is being dialed."
                                />
                                <FormInput
                                    label="Dial Timeout (seconds)"
                                    type="number"
                                    value={config.attended_transfer?.dial_timeout_seconds ?? 30}
                                    onChange={(e) => updateNestedConfig('attended_transfer', 'dial_timeout_seconds', parseInt(e.target.value) || 30)}
                                    tooltip="How long to ring the destination before aborting the transfer."
                                />
                                <FormInput
                                    label="Accept Timeout (seconds)"
                                    type="number"
                                    value={config.attended_transfer?.accept_timeout_seconds ?? 15}
                                    onChange={(e) => updateNestedConfig('attended_transfer', 'accept_timeout_seconds', parseInt(e.target.value) || 15)}
                                    tooltip="How long to wait for the destination to press a DTMF digit."
                                />
                                <FormInput
                                    label="TTS Timeout (seconds)"
                                    type="number"
                                    value={config.attended_transfer?.tts_timeout_seconds ?? 8}
                                    onChange={(e) => updateNestedConfig('attended_transfer', 'tts_timeout_seconds', parseInt(e.target.value) || 8)}
                                    tooltip="Max time to wait for Local AI Server TTS per prompt."
                                />
                                <FormInput
                                    label="Accept Digit"
                                    value={config.attended_transfer?.accept_digit || '1'}
                                    onChange={(e) => updateNestedConfig('attended_transfer', 'accept_digit', e.target.value)}
                                />
                                <FormInput
                                    label="Decline Digit"
                                    value={config.attended_transfer?.decline_digit || '2'}
                                    onChange={(e) => updateNestedConfig('attended_transfer', 'decline_digit', e.target.value)}
                                />
                            </div>

                            <div className="space-y-2">
                                <FormLabel tooltip="Spoken to the destination agent (one-way) before requesting DTMF acceptance. Placeholders: {caller_display}, {caller_name}, {caller_number}, {context_name}, {destination_description}.">
                                    Agent Announcement Template
                                </FormLabel>
                                <textarea
                                    className="w-full p-3 rounded-md border border-input bg-transparent text-sm min-h-[100px] focus:outline-none focus:ring-1 focus:ring-ring"
                                    value={config.attended_transfer?.announcement_template ?? DEFAULT_ATTENDED_ANNOUNCEMENT_TEMPLATE}
                                    onChange={(e) => updateNestedConfig('attended_transfer', 'announcement_template', e.target.value)}
                                    placeholder="Hi, this is Ava. I'm transferring {caller_display} regarding {context_name}."
                                />
                            </div>

                            <div className="space-y-2">
                                <FormLabel tooltip="Spoken to the destination agent to request acceptance/decline (DTMF).">
                                    Agent DTMF Prompt Template
                                </FormLabel>
                                <textarea
                                    className="w-full p-3 rounded-md border border-input bg-transparent text-sm min-h-[80px] focus:outline-none focus:ring-1 focus:ring-ring"
                                    value={config.attended_transfer?.agent_accept_prompt_template ?? DEFAULT_ATTENDED_AGENT_DTMF_PROMPT_TEMPLATE}
                                    onChange={(e) => updateNestedConfig('attended_transfer', 'agent_accept_prompt_template', e.target.value)}
                                    placeholder="Press 1 to accept this transfer, or 2 to decline."
                                />
                            </div>

                            <FormInput
                                label="Caller Connected Prompt (Optional)"
                                value={config.attended_transfer?.caller_connected_prompt ?? DEFAULT_ATTENDED_CALLER_CONNECTED_PROMPT}
                                onChange={(e) => updateNestedConfig('attended_transfer', 'caller_connected_prompt', e.target.value)}
                                tooltip="Optional phrase spoken to the caller right before bridging to the destination (e.g., 'Connecting you now.')."
                                placeholder="Connecting you now."
                            />

                            <FormInput
                                label="Caller Declined Prompt (Optional)"
                                value={config.attended_transfer?.caller_declined_prompt ?? DEFAULT_ATTENDED_CALLER_DECLINED_PROMPT}
                                onChange={(e) => updateNestedConfig('attended_transfer', 'caller_declined_prompt', e.target.value)}
                                tooltip="Spoken to the caller when the destination declines or the attended transfer times out (keeps the conversation moving)."
                                placeholder="I’m not able to complete that transfer right now. Would you like me to take a message?"
                            />
                        </div>
                    )}
                </div>

                {/* Cancel Transfer */}
                <div className="border border-border rounded-lg p-4 bg-card/50">
                    <FormSwitch
                        label="Cancel Transfer"
                        description="Allow callers to cancel an in-progress transfer."
                        checked={config.cancel_transfer?.enabled ?? true}
                        onChange={(e) => updateNestedConfig('cancel_transfer', 'enabled', e.target.checked)}
                        className="mb-0 border-0 p-0 bg-transparent"
                    />
                    {config.cancel_transfer?.enabled !== false && (
                        <div className="mt-4 pl-4 border-l-2 border-border ml-2">
                            <FormSwitch
                                label="Allow During Ring"
                                checked={config.cancel_transfer?.allow_during_ring ?? true}
                                onChange={(e) => updateNestedConfig('cancel_transfer', 'allow_during_ring', e.target.checked)}
                            />
                        </div>
                    )}
                </div>

                {/* Hangup Call */}
                <div className="border border-border rounded-lg p-4 bg-card/50">
                    <FormSwitch
                        label="Hangup Call"
                        description="Allow the agent to end the call gracefully."
                        checked={config.hangup_call?.enabled ?? true}
                        onChange={(e) => updateNestedConfig('hangup_call', 'enabled', e.target.checked)}
                        className="mb-0 border-0 p-0 bg-transparent"
                    />
                    {config.hangup_call?.enabled !== false && (
                        <div className="mt-4 pl-4 border-l-2 border-border ml-2 grid grid-cols-1 md:grid-cols-2 gap-4">
                            <FormInput
                                label="Farewell Message"
                                value={config.hangup_call?.farewell_message || ''}
                                onChange={(e) => updateNestedConfig('hangup_call', 'farewell_message', e.target.value)}
                            />
                            <FormSwitch
                                label="Require Confirmation"
                                checked={config.hangup_call?.require_confirmation ?? false}
                                onChange={(e) => updateNestedConfig('hangup_call', 'require_confirmation', e.target.checked)}
                            />
                            <FormInput
                                label="Farewell Hangup Delay (seconds)"
                                type="number"
                                step="0.5"
                                value={config.farewell_hangup_delay_sec ?? 2.5}
                                onChange={(e) => updateConfig('farewell_hangup_delay_sec', parseFloat(e.target.value) || 2.5)}
                                tooltip="Time to wait after farewell audio before hanging up. Increase if farewell gets cut off."
                            />
                            <FormSelect
                                label="Hangup Guardrail Mode"
                                value={config.hangup_call?.policy?.mode || DEFAULT_HANGUP_POLICY_MODE}
                                onChange={(e) => updateHangupPolicy('mode', e.target.value)}
                                options={[
                                    { value: 'relaxed', label: 'Relaxed (allow hangup more freely)' },
                                    { value: 'normal', label: 'Normal (default guardrail behavior)' },
                                    { value: 'strict', label: 'Strict (require explicit end intent)' },
                                ]}
                                tooltip="Controls how strictly the system filters hangup_call tool calls when the user has not explicitly asked to end the call."
                            />
                            <FormSwitch
                                label="Enforce Transcript Offer Before Hangup"
                                checked={config.hangup_call?.policy?.enforce_transcript_offer ?? true}
                                onChange={(e) => updateHangupPolicy('enforce_transcript_offer', e.target.checked)}
                                description="If transcript emailing is enabled, block hangup_call until the user accepts or declines a transcript."
                            />
                            <FormSwitch
                                label="Block During Contact Confirmation"
                                checked={config.hangup_call?.policy?.block_during_contact_capture ?? true}
                                onChange={(e) => updateHangupPolicy('block_during_contact_capture', e.target.checked)}
                                description="Prevents hangup while confirming an email address or other contact details."
                            />
                        </div>
                    )}
                    {config.hangup_call?.enabled !== false && (
                        <div className="mt-4 pl-4 border-l-2 border-border ml-2">
                            <FormLabel>Hangup Phrase Lists (one per line)</FormLabel>
	                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
	                                <div className="space-y-2">
	                                    <FormLabel tooltip="User phrases that indicate the call should end.">End-Call Markers</FormLabel>
	                                    <textarea
	                                        className="w-full p-3 rounded-md border border-input bg-transparent text-sm min-h-[120px] focus:outline-none focus:ring-1 focus:ring-ring"
	                                        value={hangupMarkerDirty.end_call ? hangupMarkerDraft.end_call : endCallMarkerText}
	                                        onChange={(e) => {
	                                            const text = e.target.value;
	                                            setHangupMarkerDirty((prev) => ({ ...prev, end_call: true }));
	                                            setHangupMarkerDraft((prev) => ({ ...prev, end_call: text }));
	                                            updateHangupMarkers('end_call', parseMarkerList(text));
	                                        }}
	                                        placeholder="bye\nthat's all\nend the call"
	                                    />
	                                </div>
	                                <div className="space-y-2">
	                                    <FormLabel tooltip="Assistant farewell phrases that should trigger hangup completion.">Assistant Farewell Markers</FormLabel>
	                                    <textarea
	                                        className="w-full p-3 rounded-md border border-input bg-transparent text-sm min-h-[120px] focus:outline-none focus:ring-1 focus:ring-ring"
	                                        value={hangupMarkerDirty.assistant_farewell ? hangupMarkerDraft.assistant_farewell : assistantFarewellMarkerText}
	                                        onChange={(e) => {
	                                            const text = e.target.value;
	                                            setHangupMarkerDirty((prev) => ({ ...prev, assistant_farewell: true }));
	                                            setHangupMarkerDraft((prev) => ({ ...prev, assistant_farewell: text }));
	                                            updateHangupMarkers('assistant_farewell', parseMarkerList(text));
	                                        }}
	                                        placeholder="thank you for calling\ngoodbye"
	                                    />
	                                </div>
	                                <div className="space-y-2">
	                                    <FormLabel tooltip="User phrases that indicate acceptance (e.g., transcript offer).">Affirmative Markers</FormLabel>
	                                    <textarea
	                                        className="w-full p-3 rounded-md border border-input bg-transparent text-sm min-h-[120px] focus:outline-none focus:ring-1 focus:ring-ring"
	                                        value={hangupMarkerDirty.affirmative ? hangupMarkerDraft.affirmative : affirmativeMarkerText}
	                                        onChange={(e) => {
	                                            const text = e.target.value;
	                                            setHangupMarkerDirty((prev) => ({ ...prev, affirmative: true }));
	                                            setHangupMarkerDraft((prev) => ({ ...prev, affirmative: text }));
	                                            updateHangupMarkers('affirmative', parseMarkerList(text));
	                                        }}
	                                        placeholder="yes\nyep\ncorrect"
	                                    />
	                                </div>
	                                <div className="space-y-2">
	                                    <FormLabel tooltip="User phrases that indicate decline (e.g., transcript offer).">Negative Markers</FormLabel>
	                                    <textarea
	                                        className="w-full p-3 rounded-md border border-input bg-transparent text-sm min-h-[120px] focus:outline-none focus:ring-1 focus:ring-ring"
	                                        value={hangupMarkerDirty.negative ? hangupMarkerDraft.negative : negativeMarkerText}
	                                        onChange={(e) => {
	                                            const text = e.target.value;
	                                            setHangupMarkerDirty((prev) => ({ ...prev, negative: true }));
	                                            setHangupMarkerDraft((prev) => ({ ...prev, negative: text }));
	                                            updateHangupMarkers('negative', parseMarkerList(text));
	                                        }}
	                                        placeholder="no\nno thanks\nskip"
	                                    />
	                                </div>
	                            </div>
	                        </div>
	                    )}
                </div>

                {/* Leave Voicemail */}
                <div className="border border-border rounded-lg p-4 bg-card/50">
                    <FormSwitch
                        label="Leave Voicemail"
                        description="Transfer caller to a voicemail box."
                        checked={config.leave_voicemail?.enabled ?? true}
                        onChange={(e) => updateNestedConfig('leave_voicemail', 'enabled', e.target.checked)}
                        className="mb-0 border-0 p-0 bg-transparent"
                    />
                    {config.leave_voicemail?.enabled !== false && (
                        <div className="mt-4 pl-4 border-l-2 border-border ml-2">
                            <FormInput
                                label="Voicemail Extension"
                                value={config.leave_voicemail?.extension || ''}
                                onChange={(e) => updateNestedConfig('leave_voicemail', 'extension', e.target.value)}
                            />
                        </div>
                    )}
                </div>

                {/* Extensions (basic editor) */}
                <div className="border border-border rounded-lg p-4 bg-card/50">
                    <div className="flex justify-between items-center mb-4">
                        <FormLabel>Extensions (Internal)</FormLabel>
                        <button
                            onClick={() => {
                                const existing = config.extensions?.internal || {};
                                let idx = Object.keys(existing).length + 1;
                                let key = `ext_${idx}`;
                                while (Object.prototype.hasOwnProperty.call(existing, key)) {
                                    idx += 1;
                                    key = `ext_${idx}`;
                                }
                                updateNestedConfig('extensions', 'internal', { ...existing, [key]: { name: '', description: '', dial_string: '', transfer: true, device_state_tech: 'auto' } });
                            }}
                            className="text-xs flex items-center bg-secondary px-2 py-1 rounded hover:bg-secondary/80 transition-colors"
                        >
                            <Plus className="w-3 h-3 mr-1" /> Add Extension
                        </button>
                    </div>
                    <div className="space-y-2">
                        {Object.entries(config.extensions?.internal || {}).map(([key, ext]: [string, any]) => (
                            <div key={key} className="grid grid-cols-1 md:grid-cols-12 gap-2 p-3 border rounded bg-background/50 items-center">
                                <div className="md:col-span-1">
                                    <input
                                        className="w-full border rounded px-2 py-1 text-sm bg-muted"
                                        placeholder="Key"
                                        defaultValue={key}
                                        onBlur={(e) => {
                                            const nextKey = (e.target as HTMLInputElement).value;
                                            if (nextKey !== key) renameInternalExtensionKey(key, nextKey);
                                        }}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') {
                                                (e.target as HTMLInputElement).blur();
                                            }
                                        }}
                                        title="Extension key (recommend numeric like 2765). Used for transfers and availability checks."
                                    />
                                </div>
                                <div className="md:col-span-2">
                                    <input
                                        className="w-full border rounded px-2 py-1 text-sm"
                                        placeholder="Name"
                                        value={ext.name || ''}
                                        onChange={(e) => {
                                            const updated = { ...(config.extensions?.internal || {}) };
                                            updated[key] = { ...ext, name: e.target.value };
                                            updateNestedConfig('extensions', 'internal', updated);
                                        }}
                                        title="Agent Name"
                                    />
                                </div>
                                <div className="md:col-span-3">
                                    <input
                                        className="w-full border rounded px-2 py-1 text-sm"
                                        placeholder="Dial String"
                                        value={ext.dial_string || ''}
                                        onChange={(e) => {
                                            const updated = { ...(config.extensions?.internal || {}) };
                                            updated[key] = { ...ext, dial_string: e.target.value };
                                            updateNestedConfig('extensions', 'internal', updated);
                                        }}
                                        title="PJSIP/..."
                                    />
                                </div>
                                <div className="md:col-span-2">
                                    <select
                                        className="w-full border rounded px-2 py-1 text-sm bg-background"
                                        value={ext.device_state_tech || 'auto'}
                                        onChange={(e) => {
                                            const updated = { ...(config.extensions?.internal || {}) };
                                            updated[key] = { ...ext, device_state_tech: e.target.value };
                                            updateNestedConfig('extensions', 'internal', updated);
                                        }}
                                        title="Device state technology for availability checks"
                                    >
                                        <option value="auto">Device Tech: auto</option>
                                        <option value="PJSIP">PJSIP</option>
                                        <option value="SIP">SIP</option>
                                        <option value="IAX2">IAX2</option>
                                        <option value="DAHDI">DAHDI</option>
                                    </select>
                                </div>
                                <div className="md:col-span-2">
                                    <input
                                        className="w-full border rounded px-2 py-1 text-sm"
                                        placeholder="Description"
                                        value={ext.description || ''}
                                        onChange={(e) => {
                                            const updated = { ...(config.extensions?.internal || {}) };
                                            updated[key] = { ...ext, description: e.target.value };
                                            updateNestedConfig('extensions', 'internal', updated);
                                        }}
                                        title="Description"
                                    />
                                </div>
                                <div className="md:col-span-1 flex justify-center">
                                    <FormSwitch
                                        checked={ext.transfer ?? true}
                                        onChange={(e) => {
                                            const updated = { ...(config.extensions?.internal || {}) };
                                            updated[key] = { ...ext, transfer: e.target.checked };
                                            updateNestedConfig('extensions', 'internal', updated);
                                        }}
                                        className="mb-0"
                                        label=""
                                        description=""
                                    />
                                </div>
                                <div className="md:col-span-1 flex justify-end">
                                    <button
                                        onClick={() => {
                                            const updated = { ...(config.extensions?.internal || {}) };
                                            delete updated[key];
                                            updateNestedConfig('extensions', 'internal', updated);
                                        }}
                                        className="p-2 text-destructive hover:bg-destructive/10 rounded"
                                        title="Delete Extension"
                                    >
                                        <Trash2 className="w-4 h-4" />
                                    </button>
                                </div>
                            </div>
                        ))}
                        {Object.keys(config.extensions?.internal || {}).length === 0 && (
                            <div className="text-sm text-muted-foreground">No internal extensions configured.</div>
                        )}
                    </div>
                </div>
            </div>

            {/* Business Tools */}
            <div className="space-y-6 border-t border-border pt-6">
                <h3 className="text-lg font-semibold text-primary">Business Tools</h3>

                {/* Send Email Summary */}
                <div className="border border-border rounded-lg p-4 bg-card/50">
                    <FormSwitch
                        label="Send Email Summary"
                        description="Automatically send a call summary to the admin after each call."
                        checked={config.send_email_summary?.enabled ?? true}
                        onChange={(e) => updateNestedConfig('send_email_summary', 'enabled', e.target.checked)}
                        className="mb-0 border-0 p-0 bg-transparent"
                    />
                    {config.send_email_summary?.enabled !== false && (
                        <div className="mt-4 pl-4 border-l-2 border-border ml-2 grid grid-cols-1 md:grid-cols-2 gap-4">
                            <FormInput
                                label="From Email"
                                value={config.send_email_summary?.from_email || ''}
                                onChange={(e) => updateNestedConfig('send_email_summary', 'from_email', e.target.value)}
                            />
                            <FormInput
                                label="Admin Email (Recipient)"
                                value={config.send_email_summary?.admin_email || ''}
                                onChange={(e) => updateNestedConfig('send_email_summary', 'admin_email', e.target.value)}
                            />
                            <FormSwitch
                                label="Include Transcript"
                                checked={config.send_email_summary?.include_transcript ?? true}
                                onChange={(e) => updateNestedConfig('send_email_summary', 'include_transcript', e.target.checked)}
                            />
                        </div>
                    )}
                </div>

                {/* Request Transcript */}
                <div className="border border-border rounded-lg p-4 bg-card/50">
                    <FormSwitch
                        label="Request Transcript"
                        description="Allow callers to request a transcript via email."
                        checked={config.request_transcript?.enabled ?? true}
                        onChange={(e) => updateNestedConfig('request_transcript', 'enabled', e.target.checked)}
                        className="mb-0 border-0 p-0 bg-transparent"
                    />
                    {config.request_transcript?.enabled !== false && (
                        <div className="mt-4 pl-4 border-l-2 border-border ml-2 grid grid-cols-1 md:grid-cols-2 gap-4">
                            <FormInput
                                label="From Email"
                                value={config.request_transcript?.from_email || ''}
                                onChange={(e) => updateNestedConfig('request_transcript', 'from_email', e.target.value)}
                                placeholder="agent@yourdomain.com"
                            />
                            <FormInput
                                label="Admin Email (BCC)"
                                value={config.request_transcript?.admin_email || ''}
                                onChange={(e) => updateNestedConfig('request_transcript', 'admin_email', e.target.value)}
                            />
                            <FormSwitch
                                label="Confirm Email"
                                checked={config.request_transcript?.confirm_email ?? true}
                                onChange={(e) => updateNestedConfig('request_transcript', 'confirm_email', e.target.checked)}
                            />
                            <FormSwitch
                                label="Validate Domain"
                                checked={config.request_transcript?.validate_domain ?? true}
                                onChange={(e) => updateNestedConfig('request_transcript', 'validate_domain', e.target.checked)}
                            />
                        </div>
                    )}
                </div>
            </div>

            {/* Destination Edit Modal */}
            <Modal
                isOpen={!!editingDestination}
                onClose={() => setEditingDestination(null)}
                title={editingDestination === 'new_destination' ? 'Add Destination' : 'Edit Destination'}
                footer={
                    <>
                        <button onClick={() => setEditingDestination(null)} className="px-4 py-2 border rounded hover:bg-accent">Cancel</button>
                        <button onClick={handleSaveDestination} className="px-4 py-2 bg-primary text-primary-foreground rounded hover:bg-primary/90">Save</button>
                    </>
                }
            >
                <div className="space-y-4">
                    <FormInput
                        label="Key (Name)"
                        value={destinationForm.key || ''}
                        onChange={(e) => setDestinationForm({ ...destinationForm, key: e.target.value })}
                        placeholder="e.g., sales_agent"
                        disabled={editingDestination !== 'new_destination'}
                    />
                    <FormSelect
                        label="Type"
                        options={[
                            { value: 'extension', label: 'Extension' },
                            { value: 'queue', label: 'Queue' },
                            { value: 'ringgroup', label: 'Ring Group' },
                        ]}
                        value={destinationForm.type || 'extension'}
                        onChange={(e) => setDestinationForm({ ...destinationForm, type: e.target.value })}
                    />
                    {destinationForm.type === 'extension' && (
                        <FormSwitch
                            label="Allow Attended Transfer"
                            description="Enable warm transfer for this destination (agent announcement + DTMF accept/decline)."
                            checked={destinationForm.attended_allowed ?? false}
                            onChange={(e) => setDestinationForm({ ...destinationForm, attended_allowed: e.target.checked })}
                        />
                    )}
                    <FormInput
                        label="Target Number"
                        value={destinationForm.target || ''}
                        onChange={(e) => setDestinationForm({ ...destinationForm, target: e.target.value })}
                        placeholder="e.g., 6000"
                    />
                    <FormInput
                        label="Description"
                        value={destinationForm.description || ''}
                        onChange={(e) => setDestinationForm({ ...destinationForm, description: e.target.value })}
                        placeholder="e.g., Sales Support"
                    />
                </div>
            </Modal>
        </div>
    );
};

export default ToolForm;
