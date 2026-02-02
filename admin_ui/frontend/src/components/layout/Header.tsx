import React from 'react';
import { useLocation } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';

const Header = () => {
    const location = useLocation();
    const pathSegments = location.pathname.split('/').filter(Boolean);

    const getBreadcrumbName = (segment: string) => {
        const map: Record<string, string> = {
            'providers': 'Providers',
            'pipelines': 'Pipelines',
            'contexts': 'Contexts',
            'tools': 'Tools',
            'vad': 'Voice Activity Detection',
            'streaming': 'Streaming',
            'llm': 'LLM Defaults',
            'env': 'Environment',
            'docker': 'Docker Services',
            'logs': 'System Logs',
            'yaml': 'Raw Configuration'
        };
        return map[segment] || segment.charAt(0).toUpperCase() + segment.slice(1);
    };

    return (
        <header className="h-14 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 flex items-center justify-between px-6 z-10 sticky top-0">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Admin</span>
                {pathSegments.length > 0 && <ChevronRight className="w-4 h-4" />}
                {pathSegments.map((segment, index) => (
                    <React.Fragment key={segment}>
                        <span className={index === pathSegments.length - 1 ? 'font-medium text-foreground' : ''}>
                            {getBreadcrumbName(segment)}
                        </span>
                        {index < pathSegments.length - 1 && <ChevronRight className="w-4 h-4" />}
                    </React.Fragment>
                ))}
            </div>

            {/* Global actions removed - pages handle their own saving */}
            <div className="flex items-center gap-2">
            </div>
        </header>
    );
};

export default Header;
