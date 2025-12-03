import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';
import ChangePasswordModal from '../components/auth/ChangePasswordModal';

export const RequireAuth: React.FC<{ children: JSX.Element }> = ({ children }) => {
    const { isAuthenticated, loading, mustChangePassword } = useAuth();
    const location = useLocation();

    console.log("RequireAuth: loading =", loading, "isAuthenticated =", isAuthenticated, "mustChangePassword =", mustChangePassword);

    if (loading) {
        return <div className="flex items-center justify-center h-screen">Loading...</div>;
    }

    if (!isAuthenticated) {
        console.log("RequireAuth: redirecting to login");
        return <Navigate to="/login" state={{ from: location }} replace />;
    }

    // Show mandatory password change modal if required
    if (mustChangePassword) {
        console.log("RequireAuth: showing mandatory password change");
        return (
            <div className="min-h-screen bg-background">
                <ChangePasswordModal 
                    isOpen={true} 
                    onClose={() => {}} // No-op - user must change password
                    mandatory={true}
                />
            </div>
        );
    }

    console.log("RequireAuth: rendering children");
    return children;
};
