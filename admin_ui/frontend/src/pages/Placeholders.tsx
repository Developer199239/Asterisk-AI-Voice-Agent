import React from 'react';
import { ConfigSection } from '../components/ui/ConfigSection';
import { ConfigCard } from '../components/ui/ConfigCard';

const PlaceholderPage = ({ title }: { title: string }) => (
    <div className="space-y-6">
        <div className="flex justify-between items-center">
            <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
        </div>
        <ConfigSection title="Coming Soon" description="This page is under construction.">
            <ConfigCard>
                <div className="text-center py-12 text-muted-foreground">
                    {title} configuration will be available here.
                </div>
            </ConfigCard>
        </ConfigSection>
    </div>
);

export const ProvidersPage = () => <PlaceholderPage title="Providers" />;
export const PipelinesPage = () => <PlaceholderPage title="Pipelines" />;
export const ContextsPage = () => <PlaceholderPage title="Contexts" />;
export const ToolsPage = () => <PlaceholderPage title="Tools" />;
export const VADPage = () => <PlaceholderPage title="VAD Settings" />;
export const StreamingPage = () => <PlaceholderPage title="Streaming" />;
export const LLMPage = () => <PlaceholderPage title="LLM Defaults" />;
export const TransportPage = () => <PlaceholderPage title="Audio Transport" />;
export const EnvPage = () => <PlaceholderPage title="Environment" />;
export const DockerPage = () => <PlaceholderPage title="Docker Services" />;
export const TerminalPage = () => <PlaceholderPage title="Terminal" />;
export const RawYamlPage = () => <PlaceholderPage title="Raw YAML" />;
