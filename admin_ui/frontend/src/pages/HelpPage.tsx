import { useState, useEffect, useCallback } from 'react';
import { Book, ChevronDown, ChevronRight, ExternalLink, Search, X, ChevronLeft, Loader2 } from 'lucide-react';
import { ConfigCard } from '../components/ui/ConfigCard';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import axios from 'axios';

interface DocInfo {
    file: string;
    title: string;
    description: string;
}

interface Category {
    id: string;
    title: string;
    icon: string;
    description: string;
    docs: DocInfo[];
}

interface DocContent {
    file: string;
    title: string;
    content: string;
    category: string;
    prev_doc: DocInfo | null;
    next_doc: DocInfo | null;
}

const HelpPage = () => {
    const [categories, setCategories] = useState<Category[]>([]);
    const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
    const [selectedDoc, setSelectedDoc] = useState<DocContent | null>(null);
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState<Array<{ file: string; title: string; category: string; snippet: string }>>([]);
    const [isSearching, setIsSearching] = useState(false);

    useEffect(() => {
        loadCategories();
    }, []);

    const loadCategories = async () => {
        try {
            const response = await axios.get('/api/docs/categories');
            setCategories(response.data);
            if (response.data.length > 0) {
                setExpandedCategories(new Set([response.data[0].id]));
            }
        } catch (error) {
            console.error('Failed to load documentation categories:', error);
        }
    };

    const toggleCategory = (categoryId: string) => {
        setExpandedCategories(prev => {
            const next = new Set(prev);
            if (next.has(categoryId)) {
                next.delete(categoryId);
            } else {
                next.add(categoryId);
            }
            return next;
        });
    };

    const openDoc = async (file: string) => {
        setIsLoading(true);
        setIsModalOpen(true);
        try {
            const response = await axios.get(`/api/docs/content/${encodeURIComponent(file)}`);
            setSelectedDoc(response.data);
        } catch (error) {
            console.error('Failed to load document:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const closeModal = () => {
        setIsModalOpen(false);
        setSelectedDoc(null);
    };

    const navigateDoc = (doc: DocInfo) => {
        openDoc(doc.file);
    };

    const handleSearch = useCallback(async (query: string) => {
        if (query.length < 2) {
            setSearchResults([]);
            return;
        }
        setIsSearching(true);
        try {
            const response = await axios.get(`/api/docs/search?q=${encodeURIComponent(query)}`);
            setSearchResults(response.data.results || []);
        } catch (error) {
            console.error('Search failed:', error);
        } finally {
            setIsSearching(false);
        }
    }, []);

    useEffect(() => {
        const debounce = setTimeout(() => {
            handleSearch(searchQuery);
        }, 300);
        return () => clearTimeout(debounce);
    }, [searchQuery, handleSearch]);

    useEffect(() => {
        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && isModalOpen) {
                closeModal();
            }
        };
        document.addEventListener('keydown', handleEscape);
        return () => document.removeEventListener('keydown', handleEscape);
    }, [isModalOpen]);

    const getGitHubUrl = (file: string) => {
        return `https://github.com/hkjarral/Asterisk-AI-Voice-Agent/blob/main/docs/${file}`;
    };

    return (
        <div className="space-y-6">
            <div>
                <h1 className="text-3xl font-bold tracking-tight">Help & Documentation</h1>
                <p className="text-muted-foreground mt-1">
                    Browse documentation organized by category
                </p>
            </div>

            {/* Search */}
            <div className="relative max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <input
                    type="text"
                    placeholder="Search documentation..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-10 pr-4 py-2 bg-card border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
                {isSearching && (
                    <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground animate-spin" />
                )}
            </div>

            {/* Search Results */}
            {searchQuery.length >= 2 && searchResults.length > 0 && (
                <ConfigCard>
                    <h3 className="text-sm font-medium text-muted-foreground mb-3">Search Results</h3>
                    <div className="space-y-2">
                        {searchResults.map((result) => (
                            <button
                                key={result.file}
                                onClick={() => {
                                    openDoc(result.file);
                                    setSearchQuery('');
                                }}
                                className="w-full p-3 text-left bg-background rounded-lg hover:bg-accent transition-colors"
                            >
                                <div className="font-medium">{result.title}</div>
                                <div className="text-xs text-muted-foreground mt-0.5">{result.category}</div>
                                <div className="text-sm text-muted-foreground mt-1 line-clamp-2">{result.snippet}</div>
                            </button>
                        ))}
                    </div>
                </ConfigCard>
            )}

            {/* Category Grid */}
            <div className="space-y-4">
                {categories.map((category) => (
                    <div key={category.id} className="bg-card rounded-xl border border-border overflow-hidden">
                        <button
                            onClick={() => toggleCategory(category.id)}
                            className="w-full px-6 py-4 flex items-center justify-between hover:bg-accent/50 transition-colors"
                        >
                            <div className="flex items-center gap-3">
                                <span className="text-2xl">{category.icon}</span>
                                <div className="text-left">
                                    <h3 className="font-semibold">{category.title}</h3>
                                    <p className="text-sm text-muted-foreground">{category.description}</p>
                                </div>
                            </div>
                            {expandedCategories.has(category.id) ? (
                                <ChevronDown className="w-5 h-5 text-muted-foreground" />
                            ) : (
                                <ChevronRight className="w-5 h-5 text-muted-foreground" />
                            )}
                        </button>
                        
                        {expandedCategories.has(category.id) && (
                            <div className="px-6 pb-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                                {category.docs.map((doc) => (
                                    <button
                                        key={doc.file}
                                        onClick={() => openDoc(doc.file)}
                                        className="p-3 bg-background rounded-lg text-left hover:bg-accent transition-colors group"
                                    >
                                        <div className="flex items-center justify-between">
                                            <span className="font-medium">{doc.title}</span>
                                            <ChevronRight className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors" />
                                        </div>
                                        <p className="text-xs text-muted-foreground mt-1">{doc.description}</p>
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                ))}
            </div>

            {/* Document Modal */}
            {isModalOpen && (
                <div
                    className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4"
                    onClick={closeModal}
                >
                    <div
                        className="bg-card rounded-xl border border-border w-full max-w-4xl max-h-[85vh] flex flex-col"
                        onClick={(e) => e.stopPropagation()}
                    >
                        {/* Modal Header */}
                        <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
                            <div className="flex items-center gap-3">
                                <Book className="w-5 h-5 text-primary" />
                                <h2 className="text-xl font-bold">
                                    {isLoading ? 'Loading...' : selectedDoc?.title}
                                </h2>
                            </div>
                            <div className="flex items-center gap-2">
                                {selectedDoc && (
                                    <a
                                        href={getGitHubUrl(selectedDoc.file)}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
                                    >
                                        <ExternalLink className="w-4 h-4" />
                                        GitHub
                                    </a>
                                )}
                                <button
                                    onClick={closeModal}
                                    className="p-1 hover:bg-accent rounded transition-colors"
                                >
                                    <X className="w-5 h-5" />
                                </button>
                            </div>
                        </div>

                        {/* Modal Content */}
                        <div className="flex-1 overflow-y-auto px-6 py-4">
                            {isLoading ? (
                                <div className="flex items-center justify-center py-12">
                                    <Loader2 className="w-8 h-8 animate-spin text-primary" />
                                </div>
                            ) : selectedDoc ? (
                                <article className="prose prose-invert prose-sm max-w-none
                                    prose-headings:text-foreground
                                    prose-h1:text-2xl prose-h1:font-bold prose-h1:mb-4
                                    prose-h2:text-xl prose-h2:font-semibold prose-h2:mt-6 prose-h2:mb-3
                                    prose-h3:text-lg prose-h3:font-medium prose-h3:mt-4 prose-h3:mb-2
                                    prose-p:text-muted-foreground prose-p:leading-relaxed
                                    prose-a:text-primary prose-a:no-underline hover:prose-a:underline
                                    prose-code:bg-accent prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-sm prose-code:before:content-none prose-code:after:content-none
                                    prose-pre:bg-accent prose-pre:border prose-pre:border-border prose-pre:rounded-lg
                                    prose-ul:text-muted-foreground prose-ol:text-muted-foreground
                                    prose-li:marker:text-muted-foreground
                                    prose-table:text-sm
                                    prose-th:bg-accent prose-th:px-3 prose-th:py-2 prose-th:text-left prose-th:font-medium
                                    prose-td:px-3 prose-td:py-2 prose-td:border-t prose-td:border-border
                                    prose-blockquote:border-l-primary prose-blockquote:text-muted-foreground
                                ">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                        {selectedDoc.content}
                                    </ReactMarkdown>
                                </article>
                            ) : null}
                        </div>

                        {/* Modal Footer */}
                        {selectedDoc && (selectedDoc.prev_doc || selectedDoc.next_doc) && (
                            <div className="flex items-center justify-between px-6 py-4 border-t border-border shrink-0">
                                {selectedDoc.prev_doc ? (
                                    <button
                                        onClick={() => navigateDoc(selectedDoc.prev_doc!)}
                                        className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                                    >
                                        <ChevronLeft className="w-4 h-4" />
                                        {selectedDoc.prev_doc.title}
                                    </button>
                                ) : (
                                    <div />
                                )}
                                {selectedDoc.next_doc ? (
                                    <button
                                        onClick={() => navigateDoc(selectedDoc.next_doc!)}
                                        className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                                    >
                                        {selectedDoc.next_doc.title}
                                        <ChevronRight className="w-4 h-4" />
                                    </button>
                                ) : (
                                    <div />
                                )}
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

export default HelpPage;
