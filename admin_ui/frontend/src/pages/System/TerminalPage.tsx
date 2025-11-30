import React, { useState, useRef, useEffect } from 'react';
import { Terminal as TerminalIcon, Play } from 'lucide-react';

const TerminalPage = () => {
    const [history, setHistory] = useState<string[]>(['Welcome to Asterisk AI Admin Terminal', 'Type "help" for available commands.']);
    const [input, setInput] = useState('');
    const endRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        endRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [history]);

    const handleCommand = (e: React.FormEvent) => {
        e.preventDefault();
        if (!input.trim()) return;

        const cmd = input.trim();
        const newHistory = [...history, `$ ${cmd}`];

        // Mock command processing
        switch (cmd) {
            case 'help':
                newHistory.push('Available commands: help, status, version, clear');
                break;
            case 'status':
                newHistory.push('System Status: NORMAL');
                newHistory.push('Active Calls: 0');
                newHistory.push('Uptime: 2d 4h 12m');
                break;
            case 'version':
                newHistory.push('Asterisk AI Agent v1.0.0');
                break;
            case 'clear':
                setHistory([]);
                setInput('');
                return;
            default:
                newHistory.push(`Command not found: ${cmd}`);
        }

        setHistory(newHistory);
        setInput('');
    };

    return (
        <div className="h-[calc(100vh-140px)] flex flex-col space-y-4">
            <div className="flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Web Terminal</h1>
                    <p className="text-muted-foreground mt-1">
                        Direct command-line access to the AI engine.
                    </p>
                </div>
            </div>

            <div className="flex-1 bg-[#09090b] border border-border rounded-lg shadow-inner flex flex-col overflow-hidden font-mono text-sm">
                <div className="flex-1 p-4 overflow-auto space-y-1">
                    {history.map((line, i) => (
                        <div key={i} className={`${line.startsWith('$') ? 'text-blue-400' : 'text-gray-300'}`}>
                            {line}
                        </div>
                    ))}
                    <div ref={endRef} />
                </div>

                <form onSubmit={handleCommand} className="p-2 bg-secondary/10 border-t border-border flex items-center gap-2">
                    <TerminalIcon className="w-4 h-4 text-muted-foreground" />
                    <input
                        type="text"
                        className="flex-1 bg-transparent border-none outline-none text-foreground placeholder:text-muted-foreground/50"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder="Enter command..."
                        autoFocus
                    />
                </form>
            </div>
        </div>
    );
};

export default TerminalPage;
