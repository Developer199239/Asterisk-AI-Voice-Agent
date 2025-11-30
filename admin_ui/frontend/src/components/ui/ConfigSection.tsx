import React from 'react';

interface ConfigSectionProps {
    title: string;
    description?: string;
    children: React.ReactNode;
}

export const ConfigSection = ({ title, description, children }: ConfigSectionProps) => {
    return (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-12">
            <div className="lg:col-span-4">
                <h3 className="text-lg font-semibold tracking-tight mb-2 sticky top-20">
                    {title}
                </h3>
                {description && (
                    <p className="text-sm text-muted-foreground sticky top-28">
                        {description}
                    </p>
                )}
            </div>
            <div className="lg:col-span-8 space-y-6">
                {children}
            </div>
        </div>
    );
};
