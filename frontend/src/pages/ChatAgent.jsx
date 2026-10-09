import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
    Send,
    Bot,
    User,
    Loader2,
    BarChart3,
    Mail,
    Calendar,
    Users,
    Settings,
    Sparkles,
    Plus,
    ChevronRight,
    Trash2,
    PanelLeft,
    PanelLeftClose,
    TrendingUp,
    AlertTriangle,
    CheckCircle,
    DollarSign,
    Zap,
    ArrowRight,
    X,
    ExternalLink,
    MessageSquare,
    Clock,
    Star,
    Target,
    Activity,
} from "lucide-react";
import {
    sendChatMessage,
    sendRecommendationEmail,
    getChatSessions,
    getChatSession,
    deleteChatSession,
} from "../api/client";
import { Link, useNavigate } from "react-router-dom";
import MeetingScheduler from "../components/MeetingScheduler";

// ─── Suggested prompts shown on welcome ────────────────────────────────────────
const SUGGESTIONS = [
    {
        text: "Which customers have HIGH churn risk?",
        icon: AlertTriangle,
        color: "from-red-500 to-orange-500",
    },
    {
        text: "Show me analytics overview",
        icon: BarChart3,
        color: "from-violet-500 to-blue-500",
    },
    {
        text: "Customers with highest revenue opportunity",
        icon: DollarSign,
        color: "from-emerald-500 to-teal-500",
    },
    {
        text: "Which customers should NOT be upsold?",
        icon: Target,
        color: "from-amber-500 to-yellow-500",
    },
    {
        text: "Customers on Enterprise plan",
        icon: Star,
        color: "from-pink-500 to-rose-500",
    },
    {
        text: "Show medium risk customers",
        icon: Activity,
        color: "from-sky-500 to-cyan-500",
    },
];

// ─── Typing dots ────────────────────────────────────────────────────────────────
function TypingIndicator() {
    return (
        <div className="flex gap-1.5 items-center px-4 py-3.5">
            {[0, 1, 2].map((i) => (
                <motion.div
                    key={i}
                    animate={{ y: [0, -5, 0] }}
                    transition={{
                        repeat: Infinity,
                        duration: 0.7,
                        delay: i * 0.15,
                    }}
                    className="w-2 h-2 rounded-full bg-violet-400"
                />
            ))}
        </div>
    );
}

// ─── Rich markdown renderer ────────────────────────────────────────────────────
function RichText({ text }) {
    const lines = text.split("\n");
    const renderInline = (str) =>
        str.split(/\*\*(.*?)\*\*/g).map((part, i) =>
            i % 2 === 1 ? (
                <strong key={i} className="font-semibold text-gray-900">
                    {part}
                </strong>
            ) : (
                part
            ),
        );

    return (
        <div className="space-y-0.5">
            {lines.map((line, idx) => {
                if (line.trim() === "")
                    return <div key={idx} className="h-1.5" />;

                // Section heading: non-indented, whole line bold, optional emoji prefix + trailing colon
                const headMatch = line.match(
                    /^(?:([\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}])\s+)?\*\*(.+?)\*\*\s*:?\s*$/u,
                );
                if (headMatch && !line.startsWith(" ")) {
                    const [, emoji, title] = headMatch;
                    return (
                        <div
                            key={idx}
                            className="flex items-center gap-2 mt-2.5 first:mt-0 mb-1"
                        >
                            {emoji && (
                                <span className="text-[15px] leading-none">
                                    {emoji}
                                </span>
                            )}
                            <h4 className="text-[13px] font-bold text-gray-900 tracking-tight">
                                {title}
                            </h4>
                        </div>
                    );
                }

                // Numbered top-level item: "1. Name" (with number badge)
                const numMatch = line.match(/^(\d+)\.\s+(.*)$/);
                if (numMatch && !line.startsWith(" ")) {
                    const [, num, rest] = numMatch;
                    return (
                        <div key={idx} className="flex gap-2 mt-1.5">
                            <span className="h-4 w-4 mt-0.5 rounded-full bg-violet-100 text-violet-700 text-[9px] font-bold grid place-items-center shrink-0">
                                {num}
                            </span>
                            <span className="text-sm leading-relaxed text-gray-700">
                                {renderInline(rest)}
                            </span>
                        </div>
                    );
                }

                // 2-space bullet/dash → top-level list item
                const topBullet = line.match(/^ {2}[•\-]\s+/);
                if (topBullet) {
                    return (
                        <div key={idx} className="flex gap-2 ml-1 mt-1">
                            <span className="text-violet-400 mt-0.5 shrink-0">
                                •
                            </span>
                            <span className="text-sm leading-relaxed text-gray-700">
                                {renderInline(line.slice(topBullet[0].length))}
                            </span>
                        </div>
                    );
                }

                // No-indent dash → list item (e.g. "- Total customers: 12")
                if (/^- \S/.test(line)) {
                    return (
                        <div key={idx} className="flex gap-2">
                            <span className="text-violet-400 mt-0.5 shrink-0">
                                •
                            </span>
                            <span className="text-sm leading-relaxed text-gray-700">
                                {renderInline(line.slice(2))}
                            </span>
                        </div>
                    );
                }

                // 3–4 space + bold (optional leading dash) → sub-section label (small caps, no bullet)
                if (/^ {3,4}(?:- )?\*\*/.test(line)) {
                    return (
                        <div
                            key={idx}
                            className="ml-6 text-[10.5px] font-bold text-gray-400 uppercase tracking-wide mt-1"
                        >
                            {renderInline(
                                line
                                    .trim()
                                    .replace(/^- /, "")
                                    .replace(/:$/, ""),
                            )}
                        </div>
                    );
                }

                // 3–4 space + arrow → sub-item (feature) with arrow
                if (/^ {3,4}→/.test(line)) {
                    return (
                        <div
                            key={idx}
                            className="ml-6 flex gap-1.5 text-xs text-gray-600 leading-relaxed"
                        >
                            <span className="text-violet-300 shrink-0">→</span>
                            <span>
                                {renderInline(line.replace(/^\s*→\s*/, ""))}
                            </span>
                        </div>
                    );
                }

                // 3-space bullet ("   • Recommended: …") → sub bullet
                if (/^ {3}•\s+/.test(line)) {
                    return (
                        <div
                            key={idx}
                            className="ml-6 flex gap-1.5 text-xs text-gray-600 leading-relaxed"
                        >
                            <span className="text-violet-300 shrink-0">•</span>
                            <span>
                                {renderInline(line.replace(/^\s*•\s+/, ""))}
                            </span>
                        </div>
                    );
                }

                // Any other 4-space indent → indented sub-text
                if (line.startsWith("    ")) {
                    return (
                        <div
                            key={idx}
                            className="ml-6 text-xs text-gray-500 leading-relaxed"
                        >
                            {renderInline(line.trim())}
                        </div>
                    );
                }

                return (
                    <p
                        key={idx}
                        className="text-sm leading-relaxed text-gray-700"
                    >
                        {renderInline(line)}
                    </p>
                );
            })}
        </div>
    );
}

// ─── Customer card ─────────────────────────────────────────────────────────────
function CustomerCard({ data }) {
    if (!data) return null;
    const risk = (data.churn_risk || "").toUpperCase();
    const riskColors = {
        HIGH: {
            bg: "bg-red-50",
            border: "border-red-200",
            text: "text-red-600",
            dot: "bg-red-500",
        },
        MEDIUM: {
            bg: "bg-amber-50",
            border: "border-amber-200",
            text: "text-amber-600",
            dot: "bg-amber-500",
        },
        LOW: {
            bg: "bg-emerald-50",
            border: "border-emerald-200",
            text: "text-emerald-600",
            dot: "bg-emerald-500",
        },
    };
    const rc = riskColors[risk] || riskColors.LOW;
    const conf = Math.round((data.confidence || 0) * 100);

    return (
        <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
        >
            <Link
                to={`/customers/${data.customer_id}`}
                className={`block mt-3 rounded-2xl border ${rc.border} ${rc.bg} overflow-hidden hover:shadow-md transition-shadow group`}
            >
                <div className="px-4 py-3">
                    <div className="flex items-start justify-between gap-2">
                        <div>
                            <p className="font-bold text-gray-900 text-sm group-hover:text-violet-700 transition-colors">
                                {data.customer_name}
                            </p>
                            <p className="text-xs text-gray-500 mt-0.5">
                                {data.plan_tier} · Renewal in{" "}
                                {data.renewal_days}d
                            </p>
                        </div>
                        <span
                            className={`flex items-center gap-1 text-[10px] font-bold px-2 py-1 rounded-full ${rc.text} bg-white border ${rc.border}`}
                        >
                            <span
                                className={`w-1.5 h-1.5 rounded-full ${rc.dot}`}
                            />
                            {risk}
                        </span>
                    </div>

                    {Array.isArray(data.top_products) &&
                    data.top_products.length > 0 ? (
                        <div className="mt-2 space-y-1.5">
                            {data.top_products.map((p, i) => (
                                <div
                                    key={i}
                                    className="flex items-center gap-2 bg-white/70 rounded-xl px-3 py-2 border border-white"
                                >
                                    <span className="h-4 w-4 rounded-full bg-violet-100 text-violet-700 text-[9px] font-bold grid place-items-center shrink-0">
                                        {i + 1}
                                    </span>
                                    <span className="text-xs font-medium text-violet-700 truncate">
                                        {p.product}
                                    </span>
                                    {p.confidence != null && (
                                        <span className="ml-auto text-[10px] text-gray-400 font-semibold shrink-0">
                                            {Math.round(p.confidence * 100)}%
                                        </span>
                                    )}
                                </div>
                            ))}
                        </div>
                    ) : (
                        data.recommended_product && (
                            <div className="mt-2 flex items-center gap-2 bg-white/70 rounded-xl px-3 py-2 border border-white">
                                <Sparkles
                                    size={12}
                                    className="text-violet-500 shrink-0"
                                />
                                <span className="text-xs font-medium text-violet-700">
                                    {data.recommended_product}
                                </span>
                                {conf > 0 && (
                                    <span className="ml-auto text-[10px] text-gray-400 font-semibold">
                                        {conf}%
                                    </span>
                                )}
                            </div>
                        )
                    )}
                </div>
            </Link>
        </motion.div>
    );
}

// ─── Analytics card ────────────────────────────────────────────────────────────
function AnalyticsCard({ data }) {
    if (!data) return null;
    const items = [
        {
            label: "Total",
            value: data.total_customers,
            icon: Users,
            color: "text-violet-600 bg-violet-50",
        },
        {
            label: "Analyzed",
            value: data.analyzed,
            icon: Activity,
            color: "text-blue-600 bg-blue-50",
        },
        {
            label: "High Risk",
            value: data.high_risk,
            icon: AlertTriangle,
            color: "text-red-600 bg-red-50",
        },
        {
            label: "With Recs",
            value: data.with_recommendations,
            icon: CheckCircle,
            color: "text-emerald-600 bg-emerald-50",
        },
    ];
    return (
        <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-3 space-y-2"
        >
            <div className="grid grid-cols-2 gap-2">
                {items.map(({ label, value, icon: Icon, color }) => (
                    <div
                        key={label}
                        className="bg-white rounded-xl border border-gray-100 p-3 flex items-center gap-2.5"
                    >
                        <div
                            className={`h-8 w-8 rounded-lg flex items-center justify-center ${color}`}
                        >
                            <Icon size={14} />
                        </div>
                        <div>
                            <p className="text-[10px] text-gray-400 font-medium uppercase tracking-wide">
                                {label}
                            </p>
                            <p className="text-sm font-extrabold text-gray-900">
                                {value ?? "—"}
                            </p>
                        </div>
                    </div>
                ))}
            </div>
            <div className="bg-gradient-to-r from-emerald-500 to-teal-500 rounded-xl p-3 flex items-center gap-3">
                <div className="h-9 w-9 rounded-xl bg-white/20 flex items-center justify-center">
                    <DollarSign size={16} className="text-white" />
                </div>
                <div>
                    <p className="text-[10px] text-white/70 font-medium uppercase tracking-wide">
                        Revenue Opportunity
                    </p>
                    <p className="text-lg font-extrabold text-white">
                        ${(data.total_opportunity || 0).toLocaleString()}
                    </p>
                </div>
            </div>
        </motion.div>
    );
}

// ─── Action button row ─────────────────────────────────────────────────────────
const ACTION_CONFIG = {
    send_email: {
        icon: Mail,
        color: "hover:bg-violet-50 hover:border-violet-300 hover:text-violet-700",
        label: null,
    },
    schedule_meeting: {
        icon: Calendar,
        color: "hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700",
        label: null,
    },
    view_customer: {
        icon: ExternalLink,
        color: "hover:bg-gray-100 hover:border-gray-300",
        label: null,
        link: (a) => `/customers/${a.customer_id}`,
    },
    go_to_customers: {
        icon: Users,
        color: "hover:bg-gray-100 hover:border-gray-300",
        label: null,
        link: () => "/customers",
    },
    go_to_batch: {
        icon: BarChart3,
        color: "hover:bg-violet-50 hover:border-violet-300 hover:text-violet-700",
        label: null,
        link: () => "/batch",
    },
    go_to_settings: {
        icon: Settings,
        color: "hover:bg-gray-100 hover:border-gray-300",
        label: null,
        link: () => "/settings",
    },
    suggestion: {
        icon: Zap,
        color: "hover:bg-violet-50 hover:border-violet-300 hover:text-violet-700",
        label: null,
    },
};

function ActionButtons({ actions, onAction }) {
    if (!actions?.length) return null;
    // For suggestion chips, render them specially
    const isSuggestions = actions.every((a) => a.type === "suggestion");
    if (isSuggestions) return null; // Handled in welcome message separately

    return (
        <div className="flex flex-wrap gap-2 mt-3">
            {actions.map((action, i) => {
                const cfg = ACTION_CONFIG[action.type] || {
                    icon: ArrowRight,
                    color: "hover:bg-gray-100",
                };
                const Icon = cfg.icon;
                const base = `inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white border border-gray-200 text-gray-700 text-xs font-semibold transition-all shadow-sm ${cfg.color}`;
                if (cfg.link)
                    return (
                        <Link key={i} to={cfg.link(action)} className={base}>
                            <Icon size={12} />
                            {action.label}
                        </Link>
                    );
                return (
                    <button
                        key={i}
                        onClick={() => onAction(action)}
                        className={base}
                    >
                        <Icon size={12} />
                        {action.label}
                    </button>
                );
            })}
        </div>
    );
}

// ─── Single message bubble ─────────────────────────────────────────────────────
function Message({ msg, onAction }) {
    const isBot = msg.role === "assistant";
    return (
        <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className={`flex gap-3 ${isBot ? "" : "flex-row-reverse"}`}
        >
            <div
                className={`h-8 w-8 rounded-xl flex items-center justify-center shrink-0 shadow-sm
        ${isBot ? "bg-gradient-to-br from-violet-600 to-blue-600" : "bg-gradient-to-br from-gray-600 to-gray-700"}`}
            >
                {isBot ? (
                    <Bot size={15} className="text-white" />
                ) : (
                    <User size={15} className="text-white" />
                )}
            </div>
            <div
                className={`max-w-[82%] space-y-1 ${isBot ? "" : "items-end flex flex-col"}`}
            >
                <div
                    className={`rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm
          ${
              isBot
                  ? "bg-white border border-gray-100 text-gray-800"
                  : "bg-gradient-to-r from-violet-600 to-blue-600 text-white"
          }`}
                >
                    {isBot ? <RichText text={msg.content} /> : msg.content}
                </div>
                {msg.customer_data && (
                    <CustomerCard
                        data={msg.customer_data}
                        onAction={onAction}
                    />
                )}
                {msg.analytics_data && (
                    <AnalyticsCard data={msg.analytics_data} />
                )}
                {msg.actions?.length > 0 &&
                    !msg.customer_data &&
                    !msg.actions.every((a) => a.type === "suggestion") && (
                        <ActionButtons
                            actions={msg.actions}
                            onAction={onAction}
                        />
                    )}
            </div>
        </motion.div>
    );
}

// ─── Email modal ───────────────────────────────────────────────────────────────
function EmailModal({ customerId, customerName, onClose, onSent }) {
    const [email, setEmail] = useState("");
    const [sending, setSending] = useState(false);
    const [error, setError] = useState("");

    const handleSend = async () => {
        if (!email.trim()) {
            setError("Please enter an email address.");
            return;
        }
        setSending(true);
        try {
            await sendRecommendationEmail(customerId, email.trim());
            onSent(email.trim());
            onClose();
        } catch (e) {
            setError(e.response?.data?.detail || "Failed to send email.");
        } finally {
            setSending(false);
        }
    };

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={onClose}
        >
            <motion.div
                initial={{ scale: 0.95, y: 20 }}
                animate={{ scale: 1, y: 0 }}
                exit={{ scale: 0.95, y: 20 }}
                className="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                        <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center">
                            <Mail size={18} className="text-white" />
                        </div>
                        <div>
                            <p className="font-bold text-gray-900">
                                Send Recommendation Email
                            </p>
                            <p className="text-xs text-gray-500">
                                {customerName}
                            </p>
                        </div>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-2 hover:bg-gray-100 rounded-xl text-gray-400 hover:text-gray-600 transition-colors"
                    >
                        <X size={16} />
                    </button>
                </div>
                <div className="space-y-3">
                    <div>
                        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                            Recipient Email
                        </label>
                        <input
                            autoFocus
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && handleSend()}
                            placeholder="customer@company.com"
                            className="mt-1.5 w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent"
                        />
                    </div>
                    {error && (
                        <p className="text-xs text-red-500 bg-red-50 px-3 py-2 rounded-lg">
                            {error}
                        </p>
                    )}
                    <div className="flex gap-2 pt-1">
                        <button
                            onClick={onClose}
                            className="flex-1 py-2.5 rounded-xl border border-gray-200 text-sm font-semibold text-gray-600 hover:bg-gray-50 transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleSend}
                            disabled={sending}
                            className="flex-1 py-2.5 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-50 flex items-center justify-center gap-2"
                        >
                            {sending ? (
                                <Loader2 size={14} className="animate-spin" />
                            ) : (
                                <Send size={14} />
                            )}
                            {sending ? "Sending…" : "Send Email"}
                        </button>
                    </div>
                </div>
            </motion.div>
        </motion.div>
    );
}

// ─── Main component ────────────────────────────────────────────────────────────
export default function ChatAgent() {
    const navigate = useNavigate();
    const [messages, setMessages] = useState(() => {
        const saved = localStorage.getItem("chat_messages");
        if (saved)
            try {
                return JSON.parse(saved);
            } catch {}
        return null; // null = show welcome
    });
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [conversationId, setConversationId] = useState(
        () => localStorage.getItem("chat_conversation_id") || null,
    );
    const [meetingCustomer, setMeetingCustomer] = useState(null);
    const [emailModal, setEmailModal] = useState(null); // { customer_id, customer_name }
    const [sessions, setSessions] = useState([]);
    const [isSidebarOpen, setIsSidebarOpen] = useState(false);
    const bottomRef = useRef(null);
    const inputRef = useRef(null);

    const showWelcome = !messages || messages.length === 0;

    const loadSessions = useCallback(async () => {
        try {
            const fetched = (await getChatSessions()) || [];
            setSessions(fetched);
            // On a new device localStorage has no conversation_id — auto-restore the most recent session
            if (
                !localStorage.getItem("chat_conversation_id") &&
                fetched.length > 0
            ) {
                const latest = fetched[0];
                try {
                    const history = await getChatSession(
                        latest.conversation_id,
                    );
                    if (history?.length > 0) {
                        setMessages(history);
                        setConversationId(latest.conversation_id);
                        localStorage.setItem(
                            "chat_conversation_id",
                            latest.conversation_id,
                        );
                    }
                } catch {}
            }
        } catch {}
    }, []);

    useEffect(() => {
        loadSessions();
    }, [loadSessions]);
    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);
    useEffect(() => {
        if (messages)
            localStorage.setItem("chat_messages", JSON.stringify(messages));
    }, [messages]);
    useEffect(() => {
        if (conversationId)
            localStorage.setItem("chat_conversation_id", conversationId);
    }, [conversationId]);

    const send = async (text) => {
        const msg = (text || input).trim();
        if (!msg || loading) return;
        setInput("");
        const userMsg = { role: "user", content: msg };
        setMessages((prev) => [...(prev || []), userMsg]);
        setLoading(true);
        try {
            const res = await sendChatMessage(msg, conversationId);
            if (res.conversation_id) {
                setConversationId(res.conversation_id);
                localStorage.setItem(
                    "chat_conversation_id",
                    res.conversation_id,
                );
            }
            setMessages((prev) => [
                ...(prev || []),
                {
                    role: "assistant",
                    content: res.reply,
                    customer_data: res.customer_data,
                    analytics_data: res.analytics_data,
                    actions: res.actions || [],
                },
            ]);
            loadSessions();
        } catch {
            setMessages((prev) => [
                ...(prev || []),
                {
                    role: "assistant",
                    content:
                        "Sorry, I had trouble processing that. Please try again.",
                    actions: [],
                },
            ]);
        } finally {
            setLoading(false);
            setTimeout(() => inputRef.current?.focus(), 100);
        }
    };

    const handleClearChat = () => {
        localStorage.removeItem("chat_messages");
        localStorage.removeItem("chat_conversation_id");
        setConversationId(null);
        setMessages(null);
    };

    const loadConversation = async (id) => {
        setLoading(true);
        try {
            const history = await getChatSession(id);
            setMessages(history);
            setConversationId(id);
            setIsSidebarOpen(false);
        } catch {
            alert("Failed to load conversation.");
        } finally {
            setLoading(false);
        }
    };

    const handleDeleteSession = async (e, id) => {
        e.stopPropagation();
        if (!window.confirm("Delete this chat?")) return;
        try {
            await deleteChatSession(id);
            if (conversationId === id) handleClearChat();
            loadSessions();
        } catch {
            alert("Failed to delete chat.");
        }
    };

    const handleAction = async (action) => {
        if (action.type === "suggestion") {
            send(action.prompt || action.label);
            return;
        }
        if (action.type === "send_email") {
            setEmailModal({
                customer_id: action.customer_id,
                customer_name: action.customer_name || action.customer_id,
            });
            return;
        }
        if (action.type === "schedule_meeting") {
            setMeetingCustomer({
                customer_id: action.customer_id,
                company_name: action.customer_name || action.customer_id,
            });
            return;
        }
    };

    return (
        <div className="flex h-[calc(100vh-64px)] w-full rounded-2xl overflow-hidden bg-white border border-gray-200/60 shadow-xl">
            {/* ─── Sidebar ──────────────────────────────── */}
            <AnimatePresence>
                {isSidebarOpen && (
                    <motion.div
                        initial={{ width: 0, opacity: 0 }}
                        animate={{ width: 256, opacity: 1 }}
                        exit={{ width: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="border-r border-gray-100 bg-gray-50 flex flex-col shrink-0 overflow-hidden"
                    >
                        <div className="p-3 border-b border-gray-100">
                            <button
                                onClick={handleClearChat}
                                className="w-full flex items-center justify-center gap-2 bg-white border border-gray-200 text-gray-700 text-sm font-semibold py-2.5 rounded-xl hover:bg-gray-50 hover:border-violet-200 hover:text-violet-700 transition-all"
                            >
                                <Plus size={15} /> New Chat
                            </button>
                        </div>
                        <div className="flex-1 overflow-y-auto p-3 space-y-1">
                            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2 ml-1 flex items-center gap-1.5">
                                <Clock size={10} /> Recent Chats
                            </p>
                            {sessions.map((s) => {
                                const title =
                                    s.first_message ||
                                    (s.last_customer
                                        ? `Chat: ${s.last_customer}`
                                        : "Chat session");
                                const isActive =
                                    conversationId === s.conversation_id;
                                return (
                                    <div
                                        key={s.conversation_id}
                                        className={`group flex items-center gap-1 rounded-xl px-2 py-1.5 cursor-pointer transition-all
                      ${isActive ? "bg-violet-100 border border-violet-200" : "hover:bg-gray-200/50"}`}
                                    >
                                        <button
                                            onClick={() =>
                                                loadConversation(
                                                    s.conversation_id,
                                                )
                                            }
                                            className="flex-1 text-left min-w-0"
                                        >
                                            <div
                                                className={`truncate text-xs font-medium ${isActive ? "text-violet-800" : "text-gray-700"}`}
                                            >
                                                {title.length > 28
                                                    ? title.slice(0, 28) + "…"
                                                    : title}
                                            </div>
                                            <div className="text-[10px] text-gray-400">
                                                {s.turns} messages
                                            </div>
                                        </button>
                                        <button
                                            onClick={(e) =>
                                                handleDeleteSession(
                                                    e,
                                                    s.conversation_id,
                                                )
                                            }
                                            className="opacity-0 group-hover:opacity-100 p-1 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-all"
                                        >
                                            <Trash2 size={12} />
                                        </button>
                                    </div>
                                );
                            })}
                            {sessions.length === 0 && (
                                <p className="text-xs text-gray-400 ml-1 mt-2">
                                    No past chats yet
                                </p>
                            )}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* ─── Main area ────────────────────────────── */}
            <div className="flex-1 flex flex-col min-w-0">
                {/* Header */}
                <div className="bg-white px-5 py-3.5 border-b border-gray-100 flex items-center justify-between shrink-0">
                    <div className="flex items-center gap-3">
                        <button
                            onClick={() => setIsSidebarOpen((v) => !v)}
                            className="p-2 -ml-1 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-xl transition-all"
                        >
                            {isSidebarOpen ? (
                                <PanelLeftClose size={18} />
                            ) : (
                                <PanelLeft size={18} />
                            )}
                        </button>
                        <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-violet-600 to-blue-600 text-white flex items-center justify-center shadow-md shadow-violet-400/20">
                            <Bot size={18} />
                        </div>
                        <div>
                            <p className="font-bold text-gray-900 text-sm leading-tight">
                                AI Sales Assistant
                            </p>
                        </div>
                    </div>
                    {messages?.length > 0 && (
                        <button
                            onClick={handleClearChat}
                            className="flex items-center gap-1.5 text-xs font-semibold text-gray-400 hover:text-gray-700 hover:bg-gray-100 px-3 py-1.5 rounded-xl transition-all"
                        >
                            <Plus size={13} /> New Chat
                        </button>
                    )}
                </div>

                {/* Messages / Welcome */}
                <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5 bg-gray-50/40">
                    {showWelcome ? (
                        <motion.div
                            initial={{ opacity: 0, y: 16 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="flex flex-col items-center justify-center h-full pb-8"
                        >
                            <div className="h-16 w-16 rounded-2xl bg-gradient-to-br from-violet-600 to-blue-600 flex items-center justify-center shadow-xl shadow-violet-400/30 mb-5">
                                <Sparkles size={30} className="text-white" />
                            </div>
                            <h2 className="text-2xl font-extrabold text-gray-900 mb-1">
                                AI Sales Assistant
                            </h2>
                            <p className="text-sm text-gray-500 mb-8 text-center max-w-xs">
                                Ask me about customers, churn risk, revenue
                                opportunities, or take actions like scheduling
                                meetings.
                            </p>
                            <div className="grid grid-cols-2 gap-2.5 w-full max-w-lg">
                                {SUGGESTIONS.map(
                                    ({ text, icon: Icon, color }) => (
                                        <button
                                            key={text}
                                            onClick={() => send(text)}
                                            className="flex items-center gap-3 bg-white border border-gray-200 hover:border-violet-300 rounded-2xl px-4 py-3 text-left transition-all hover:shadow-md group"
                                        >
                                            <div
                                                className={`h-8 w-8 rounded-xl bg-gradient-to-br ${color} flex items-center justify-center shrink-0 group-hover:scale-110 transition-transform`}
                                            >
                                                <Icon
                                                    size={14}
                                                    className="text-white"
                                                />
                                            </div>
                                            <span className="text-xs font-semibold text-gray-700 leading-tight">
                                                {text}
                                            </span>
                                        </button>
                                    ),
                                )}
                            </div>
                        </motion.div>
                    ) : (
                        <>
                            {messages.map((msg, i) => (
                                <Message
                                    key={i}
                                    msg={msg}
                                    onAction={handleAction}
                                />
                            ))}
                            {loading && (
                                <div className="flex gap-3">
                                    <div className="h-8 w-8 rounded-xl bg-gradient-to-br from-violet-600 to-blue-600 flex items-center justify-center shrink-0">
                                        <Bot size={15} className="text-white" />
                                    </div>
                                    <div className="bg-white border border-gray-100 shadow-sm rounded-2xl">
                                        <TypingIndicator />
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                    <div ref={bottomRef} />
                </div>

                {/* Input */}
                <div className="px-5 py-4 border-t border-gray-100 bg-white shrink-0">
                    <form
                        onSubmit={(e) => {
                            e.preventDefault();
                            send();
                        }}
                        className="flex gap-2.5"
                    >
                        <input
                            ref={inputRef}
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            placeholder="Ask about customers, churn, analytics, products…"
                            disabled={loading}
                            className="flex-1 border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent disabled:opacity-50 bg-gray-50 focus:bg-white transition-colors"
                        />
                        <button
                            type="submit"
                            disabled={!input.trim() || loading}
                            className="h-10 w-10 rounded-xl bg-gradient-to-br from-violet-600 to-blue-600 flex items-center justify-center disabled:opacity-40 hover:shadow-lg hover:shadow-violet-500/25 transition-all shrink-0"
                        >
                            {loading ? (
                                <Loader2
                                    size={16}
                                    className="text-white animate-spin"
                                />
                            ) : (
                                <Send size={15} className="text-white" />
                            )}
                        </button>
                    </form>
                </div>
            </div>

            {/* ─── Modals ───────────────────────────────── */}
            <AnimatePresence>
                {emailModal && (
                    <EmailModal
                        customerId={emailModal.customer_id}
                        customerName={emailModal.customer_name}
                        onClose={() => setEmailModal(null)}
                        onSent={(email) =>
                            setMessages((prev) => [
                                ...prev,
                                {
                                    role: "assistant",
                                    content: `✅ Recommendation email successfully sent to **${email}** for **${emailModal.customer_name}**.`,
                                    actions: [],
                                },
                            ])
                        }
                    />
                )}
                {meetingCustomer && (
                    <MeetingScheduler
                        customer={meetingCustomer}
                        onClose={() => setMeetingCustomer(null)}
                    />
                )}
            </AnimatePresence>
        </div>
    );
}
