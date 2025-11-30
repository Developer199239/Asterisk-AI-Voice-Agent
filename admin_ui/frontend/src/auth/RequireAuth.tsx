import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';

export const RequireAuth: React.FC<{ children: JSX.Element }> = ({ children }) => {
    const { isAuthenticated, loading } = useAuth();
    const location = useLocation();

    console.log("RequireAuth: loading =", loading, "isAuthenticated =", isAuthenticated);

    if (loading) {
        return <div className="flex items-center justify-center h-screen">Loading...</div>;
    }

    if (!isAuthenticated) {
        console.log("RequireAuth: redirecting to login");
        return <Navigate to="/login" state={{ from: location }} replace />;
    }

    console.log("RequireAuth: rendering children");
    return children;
};
