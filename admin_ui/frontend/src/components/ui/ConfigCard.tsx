import React from 'react';

interface ConfigCardProps {
    children: React.ReactNode;
    className?: string;
}

export const ConfigCard = ({ children, className = '' }: ConfigCardProps) => {
    return (
        <div className={`bg-card border border-border rounded-lg shadow-sm p-6 ${className}`}>
            {children}
        </div>
    );
};
