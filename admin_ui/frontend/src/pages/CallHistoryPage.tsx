import React from 'react';
import { Phone, Clock, Calendar } from 'lucide-react';

const CallHistoryPage = () => {
    return (
        <div className="space-y-6">
            <h1 className="text-3xl font-bold">Call History</h1>
            <div className="bg-card border border-border rounded-lg p-12 text-center">
                <div className="mx-auto w-16 h-16 bg-muted rounded-full flex items-center justify-center mb-4">
                    <Phone className="w-8 h-8 text-muted-foreground" />
                </div>
                <h2 className="text-xl font-semibold mb-2">Call History Not Available</h2>
                <p className="text-muted-foreground max-w-md mx-auto">
                    Call history tracking requires a database connection which is not currently configured.
                    Please check back in a future update.
                </p>
            </div>
        </div>
    );
};

export default CallHistoryPage;
