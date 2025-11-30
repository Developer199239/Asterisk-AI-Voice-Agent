import React, { useState } from 'react';
import { HelpCircle, ExternalLink } from 'lucide-react';

interface HelpTooltipProps {
    content: React.ReactNode;
    link?: string;
    linkText?: string;
}

const HelpTooltip: React.FC<HelpTooltipProps> = ({ content, link, linkText = 'Learn more' }) => {
    const [isOpen, setIsOpen] = useState(false);

    return (
        <div className="relative inline-block">
            <button
                type="button"
                className="inline-flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
                onMouseEnter={() => setIsOpen(true)}
                onMouseLeave={() => setIsOpen(false)}
                onClick={(e) => {
                    e.preventDefault();
                    setIsOpen(!isOpen);
                }}
            >
                <HelpCircle className="w-4 h-4" />
            </button>

            {isOpen && (
                <div className="absolute z-50 w-64 p-3 mb-2 text-sm bg-popover border border-border rounded-md shadow-lg -left-28 bottom-full">
                    <div className="text-foreground mb-2">{content}</div>
                    {link && (
                        <a
                            href={link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center text-xs text-primary hover:underline"
                        >
                            {linkText}
                            <ExternalLink className="w-3 h-3 ml-1" />
                        </a>
                    )}
                    <div className="absolute w-2 h-2 bg-popover border-r border-b border-border transform rotate-45 -bottom-1 left-32"></div>
                </div>
            )}
        </div>
    );
};

export default HelpTooltip;
