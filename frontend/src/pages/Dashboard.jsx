import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
    AlertTriangle,
    DollarSign,
    Sparkles,
    Play,
    Loader2,
    AlertOctagon,
    ChevronRight,
    PieChart as PieChartIcon,
    BarChart3,
    CalendarClock,
    Gift,
    GraduationCap,
    ClipboardCheck,
    PhoneCall,
    Eye,
    Mail,
    X,
    Copy,
    Check,
    ArrowUpRight,
    Activity,
    ShieldCheck,
    Target,
} from "lucide-react";
import {
    PieChart,
    Pie,
    Cell,
    Legend,
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
} from "recharts";
import {
    generateRecommendations,
    batchSendEmails,
    getCatalog,
} from "../api/client";
import { useAppData } from "../context/AppDataContext";

const CHURN_COLORS = { HIGH: "#ef4444", MEDIUM: "#f59e0b", LOW: "#10b981" };

const RETENTION_ACTION_META = {
    executive_meeting: {
        icon: CalendarClock,
        label: "Schedule meeting",
        className: "bg-indigo-50 text-indigo-700 ring-indigo-500/20",
    },
    complimentary_offer: {
        icon: Gift,
        label: "Complimentary offer",
        className: "bg-pink-50 text-pink-700 ring-pink-500/20",
    },
    training_session: {
        icon: GraduationCap,
        label: "Offer training",
        className: "bg-sky-50 text-sky-700 ring-sky-500/20",
    },
    account_review: {
        icon: ClipboardCheck,
        label: "Account review",
        className: "bg-gray-100 text-gray-700 ring-gray-500/20",
    },
    proactive_outreach: {
        icon: PhoneCall,
        label: "Check in",
        className: "bg-teal-50 text-teal-700 ring-teal-500/20",
    },
    monitor: {
        icon: Eye,
        label: "Monitor",
        className: "bg-gray-100 text-gray-500 ring-gray-500/20",
    },
};

// Soft, no-commitment "future work" email -- deliberately NOT a meeting
// request. Just flags the product/context so the account manager has
// something ready to send whenever they decide to follow up, without
// implying a call needs to be scheduled right now.
function buildFutureWorkEmail(c) {
    const product = c.current_product ? ` on ${c.current_product}` : "";
    const subject = `Checking in${c.current_product ? ` on ${c.current_product}` : ""}`;
    const body = `Hi team,

Hope things are going well${product}. Nothing urgent on our end -- just wanted to stay on your radar in case anything changes with your usage or plans.

${c.no_recommendation_reason || ""}

Feel free to reach out any time if it'd help to revisit options${product || " for your account"} down the line -- no need to set anything up now, just flagging that we're here whenever it's useful.

Best,
[Your name]`;
    return { subject, body };
}

function FutureWorkModal({ customer, onClose }) {
    const [copied, setCopied] = useState(false);
    if (!customer) return null;
    const { subject, body } = buildFutureWorkEmail(customer);
    const copy = () => {
        navigator.clipboard?.writeText(`Subject: ${subject}\n\n${body}`);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
    };
    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/40 backdrop-blur-sm"
            onClick={onClose}
        >
            <div
                onClick={(e) => e.stopPropagation()}
                className="bg-white rounded-2xl shadow-xl w-full max-w-lg overflow-hidden max-h-[85vh] flex flex-col"
            >
                <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
                    <div className="flex items-center gap-2">
                        <Mail size={17} className="text-teal-600" />
                        <h3 className="text-[15px] font-bold text-gray-900">
                            Suggested future-work email
                        </h3>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                    >
                        <X size={16} />
                    </button>
                </div>
                <div className="p-6 overflow-y-auto">
                    <p className="text-[12px] text-gray-500 mb-4">
                        Not a meeting request — a light-touch note to keep the
                        door open for {customer.company_name}. Edit before
                        sending.
                    </p>
                    <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-1">
                        Subject
                    </p>
                    <p className="text-[13px] text-gray-800 mb-4 bg-gray-50 border border-gray-100 rounded-lg px-3 py-2">
                        {subject}
                    </p>
                    <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-1">
                        Body
                    </p>
                    <pre className="text-[12.5px] text-gray-700 leading-relaxed bg-gray-50 border border-gray-100 rounded-lg px-3 py-3 whitespace-pre-wrap font-sans">
                        {body}
                    </pre>
                </div>
                <div className="px-5 py-3.5 border-t border-gray-100 flex justify-end">
                    <button
                        onClick={copy}
                        className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-gray-900 text-white text-[12px] font-semibold hover:bg-gray-800 transition-colors"
                    >
                        {copied ? <Check size={13} /> : <Copy size={13} />}{" "}
                        {copied ? "Copied" : "Copy email"}
                    </button>
                </div>
            </div>
        </div>
    );
}

function Card({ children, className = "" }) {
    return (
        <div
            className={`traject-card bg-white rounded-2xl border border-gray-200/60 shadow-card ${className}`}
        >
            {children}
        </div>
    );
}

function KPI({
    icon: Icon,
    label,
    value,
    sub,
    color = "text-gray-900",
    iconBg = "bg-gray-100",
}) {
    return (
        <Card className="p-6 flex items-start gap-4 traject-kpi">
            <div
                className={`h-10 w-10 rounded-xl ${iconBg} flex items-center justify-center shrink-0`}
            >
                <Icon size={20} className={color} />
            </div>
            <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    {label}
                </p>
                <p
                    className={`text-xl font-extrabold ${color} mt-0.5 tabular-nums`}
                >
                    {value}
                </p>
                {sub && (
                    <p className="text-[11px] text-gray-400 mt-0.5">{sub}</p>
                )}
            </div>
        </Card>
    );
}

function Confidence({ value }) {
    const pct = Math.round((value || 0) * 100);
    const color =
        pct >= 70
            ? "bg-emerald-500"
            : pct >= 40
              ? "bg-amber-500"
              : "bg-gray-300";
    return (
        <div className="flex items-center gap-2 w-28">
            <div className="flex-1 h-1.5 rounded-full bg-gray-100 overflow-hidden">
                <div
                    className={`h-full rounded-full ${color}`}
                    style={{ width: `${pct}%` }}
                />
            </div>
            <span className="text-[11px] font-bold text-gray-500 tabular-nums w-8 text-right">
                {pct}%
            </span>
        </div>
    );
}

function ProductTooltip({ active, payload, catalogIndex }) {
    if (!active || !payload?.length) return null;
    const { name, count } = payload[0].payload;
    const prod = catalogIndex?.[name];
    const features = prod?.features
        ? prod.features
              .split("|")
              .map((f) => f.trim())
              .filter(Boolean)
        : [];
    return (
        <div className="bg-white border border-gray-200 rounded-xl shadow-lg p-3 min-w-[180px]">
            <p className="text-[12px] font-bold text-gray-900 mb-0.5">{name}</p>
            <p className="text-[11px] text-gray-400 mb-2">
                {count} customer{count === 1 ? "" : "s"}
            </p>
            {features.length > 0 && (
                <ul className="space-y-0.5">
                    {features.slice(0, 4).map((f, i) => (
                        <li
                            key={i}
                            className="text-[11px] text-gray-600 flex gap-1.5"
                        >
                            <span className="text-violet-400 shrink-0">
                                &rarr;
                            </span>
                            {f}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

export default function Dashboard() {
    const {
        customers,
        analytics: summary,
        dataStatus,
        loading,
        refresh,
    } = useAppData();
    const [running, setRunning] = useState(false);
    const [runError, setRunError] = useState(null);
    const [emailFor, setEmailFor] = useState(null);
    const [batchEmailing, setBatchEmailing] = useState(false);
    const [catalogIndex, setCatalogIndex] = useState({});
    const [showAllProducts, setShowAllProducts] = useState(false);

    useEffect(() => {
        getCatalog()
            .then((data) => {
                const idx = {};
                (data?.products || data || []).forEach((p) => {
                    if (p.product_name) idx[p.product_name] = p;
                });
                setCatalogIndex(idx);
            })
            .catch(() => {});
    }, []);

    const runFull = async () => {
        setRunning(true);
        setRunError(null);
        try {
            await generateRecommendations();
            await refresh();
        } catch (e) {
            setRunError(e?.response?.data?.detail || "Analysis failed to run.");
        } finally {
            setRunning(false);
        }
    };

    if (loading)
        return (
            <div className="space-y-4 animate-pulse">
                <div className="h-8 w-48 skeleton" />
                <div className="grid grid-cols-3 gap-4">
                    {[...Array(3)].map((_, i) => (
                        <div key={i} className="h-24 skeleton" />
                    ))}
                </div>
                <div className="h-72 skeleton" />
            </div>
        );

    const segs = summary?.churn_distribution || [];
    const high = segs.find((s) => s.segment === "HIGH")?.count || 0;
    const total = summary?.total_revenue_opportunity || 0;
    const totalCustomers = summary?.total_customers ?? customers.length;
    const analyzedCount = summary?.analyzed_customers ?? 0;
    const recsGenerated = summary?.recommendations_generated ?? 0;
    const noRecCustomers = summary?.no_recommendation_customers || [];
    const reviewedPercent = totalCustomers > 0 ? Math.min(100, Math.round(analyzedCount / totalCustomers * 100)) : 0;
    const canRun = dataStatus?.can_run_analysis !== false;

    // Top 5 most confident upsell opportunities -- always the 5 highest-
    // confidence analyzed customers with a recommendation, ranked by actual
    // confidence score. No minimum-confidence threshold here: if the best
    // available opportunities are only low-confidence pitches, they still
    // show up (ranked honestly) rather than leaving the panel empty.
    const topOpps = [...customers]
        .filter((c) => c.analyzed && c.recommended_product)
        .sort((a, b) => (b.confidence ?? -1) - (a.confidence ?? -1))
        .slice(0, 5);

    // Churn risk split, for the pie chart -- reuses the same segment counts
    // as the "High Churn Risk" KPI above so the two never disagree.
    const churnPieData = segs
        .map((s) => ({ name: s.segment, value: s.count }))
        .filter((s) => s.value > 0);

    // Which products customers are currently on -- the clearest "what's
    // actually being used" view available from customer records (every
    // analyzed customer has a current_product from the catalog).
    const productCounts = {};
    for (const c of customers) {
        const name = c.current_product;
        if (!name) continue;
        productCounts[name] = (productCounts[name] || 0) + 1;
    }
    const allProductsData = Object.entries(productCounts)
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count);
    const topProductsData = showAllProducts
        ? allProductsData
        : allProductsData.slice(0, 6);

    // Which industries customers are in
    const industryCounts = {};
    for (const c of customers) {
        const ind = c.industry && c.industry !== "Unknown" ? c.industry : null;
        if (!ind) continue;
        industryCounts[ind] = (industryCounts[ind] || 0) + 1;
    }
    const topIndustriesData = Object.entries(industryCounts)
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count)
        .slice(0, 6);

    // Nothing analyzed yet -- prompt to run, don't show empty numbers.
    if (analyzedCount === 0) {
        return (
            <div className="space-y-6 animate-fade-in">
                <div>
                    <h1 className="text-[22px] font-extrabold text-gray-900 tracking-tight">
                        Dashboard
                    </h1>
                    <p className="text-[13px] text-gray-500 mt-0.5">
                        Upsell recommendations, ranked by confidence
                    </p>
                </div>
                {dataStatus?.gaps?.length > 0 && (
                    <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3">
                        <div className="flex items-center gap-2 mb-1.5">
                            <AlertOctagon size={15} className="text-red-500" />
                            <p className="text-[12.5px] font-bold text-red-800">
                                Missing data
                            </p>
                        </div>
                        <ul className="space-y-1">
                            {dataStatus.gaps.map((g, i) => (
                                <li
                                    key={i}
                                    className="text-[12px] text-red-700"
                                >
                                    • {g}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
                <div className="bg-white rounded-2xl border border-gray-200/60 shadow-card py-16 px-6 text-center">
                    <Sparkles size={36} className="text-blue-300 mx-auto" />
                    <h2 className="mt-4 text-[16px] font-bold text-gray-900">
                        No analysis has been run yet
                    </h2>
                    <p className="mt-1.5 text-[13px] text-gray-500 max-w-md mx-auto">
                        {totalCustomers} customer
                        {totalCustomers === 1 ? "" : "s"} loaded. Run the
                        analysis to rank them by how confidently we can upsell
                        each one.
                    </p>
                    {!canRun && (
                        <p className="mt-3 text-[12px] font-semibold text-red-600">
                            Upload a product catalog before running analysis.
                        </p>
                    )}
                    {runError && (
                        <p className="mt-3 text-[12px] font-semibold text-red-600">
                            {runError}
                        </p>
                    )}
                    <button
                        onClick={runFull}
                        disabled={running || !canRun}
                        className="mt-5 inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-blue-600 text-white text-[13px] font-semibold shadow-sm shadow-blue-500/20 hover:bg-blue-700 disabled:opacity-50 transition-all"
                    >
                        {running ? (
                            <Loader2 size={16} className="animate-spin" />
                        ) : (
                            <Play size={16} />
                        )}
                        {running
                            ? "Running analysis…"
                            : `Run Analysis (${totalCustomers} customers)`}
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-6 animate-fade-in">
            <div className="traject-section-heading flex items-center justify-between gap-4 flex-wrap">
                <div>
                    <p className="text-[10px] font-extrabold tracking-[.24em] text-[#708075] uppercase mb-1">Revenue command center / 01</p>
                    <h1 className="text-[29px] sm:text-[34px] font-extrabold tracking-tight text-[#1a2923]">Your overview<span className="text-[#7ba93c]">.</span></h1>
                </div>
                <Link to="/customers" className="traject-outline-action inline-flex items-center gap-2 px-4 py-2.5 font-bold text-[12px] rounded-xl">Explore accounts <ArrowUpRight size={15}/></Link>
            </div>
            <section className="traject-hero relative overflow-hidden rounded-[28px] p-6 sm:p-8 lg:p-9">
                <div className="traject-hero-pattern" aria-hidden="true" />
                <div className="relative z-10 grid lg:grid-cols-[1.25fr_.75fr] gap-8 items-center">
                    <div>
                        <div className="inline-flex items-center gap-2 traject-hero-eyebrow text-[10px] font-extrabold uppercase tracking-[.19em] mb-5"><Activity size={14}/> SIGNALS → DECISIONS → GROWTH</div>
                        <h2 className="text-[29px] sm:text-[39px] tracking-[-.045em] text-white font-extrabold leading-[1.12] max-w-[620px]">Spot the next move.<br/><span className="text-[#bdf583]">Before it becomes obvious.</span></h2>
                        <p className="text-[13px] sm:text-[14px] text-[#b7c9bd] leading-relaxed max-w-[495px] mt-4">Traject connects account signals, churn exposure and expansion potential so every recommendation has a next action.</p>
                        <div className="flex items-center flex-wrap gap-3 mt-7">
                            <button onClick={runFull} disabled={running || !canRun} className="traject-primary-action inline-flex items-center gap-2 rounded-xl px-5 py-3 text-[12px] font-extrabold disabled:opacity-60">
                                {running ? <Loader2 size={16} className="animate-spin"/> : <Play size={15} fill="currentColor"/>}
                                {running ? 'Running analysis…' : analyzedCount < totalCustomers ? 'Analyze remaining accounts' : 'Re-run intelligence'}
                            </button>
                            <Link to="/chat" className="inline-flex items-center gap-2 text-white text-[12px] font-bold px-2 py-2 hover:text-[#bdf583]">Open AI workbench <ArrowUpRight size={16}/></Link>
                        </div>
                    </div>
                    <div className="traject-signal-panel rounded-[22px] p-5 sm:p-6">
                        <div className="flex justify-between items-center mb-5"><span className="text-[11px] font-bold text-[#d5e4d8]">Portfolio coverage</span><Target size={18} className="text-[#bdf583]"/></div>
                        <div className="flex items-end gap-2"><span className="font-extrabold text-white text-[51px] leading-none tracking-tight tabular-nums">{reviewedPercent}%</span><span className="text-[11px] mb-1.5 text-[#abc2af]">analyzed</span></div>
                        <div className="h-[6px] bg-white/15 rounded-full overflow-hidden mt-5"><div className="h-full rounded-full bg-[#bdf583] transition-all" style={{width:`${reviewedPercent}%`}}/></div>
                        <p className="text-[12px] mt-3 text-[#b7c9bd]">{analyzedCount} of {totalCustomers} accounts reviewed</p>
                        <div className="border-t border-white/15 pt-4 mt-5 grid grid-cols-2 gap-4"><div><p className="text-[10px] text-[#a5bcb0]">Actionable insights</p><p className="text-white text-[21px] font-bold mt-1">{recsGenerated}</p></div><div><p className="text-[10px] text-[#a5bcb0]">Retention watch</p><p className="text-white text-[21px] font-bold mt-1">{high}</p></div></div>
                    </div>
                </div>
            </section>

            {dataStatus?.gaps?.length > 0 && (
                <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3">
                    <div className="flex items-center gap-2 mb-1.5">
                        <AlertOctagon size={15} className="text-red-500" />
                        <p className="text-[12.5px] font-bold text-red-800">
                            Missing data
                        </p>
                    </div>
                    <ul className="space-y-1">
                        {dataStatus.gaps.map((g, i) => (
                            <li key={i} className="text-[12px] text-red-700">
                                • {g}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            {runError && (
                <p className="text-[12px] font-semibold text-red-600">
                    {runError}
                </p>
            )}

            <div className="flex items-center justify-between gap-3 pt-2"><div><p className="text-[10px] uppercase font-extrabold tracking-[.18em] text-[#8b988e]">Portfolio snapshot</p><h2 className="text-[19px] font-extrabold text-[#25332a] mt-1">What deserves attention</h2></div><span className="hidden sm:inline-flex items-center gap-1.5 text-[11px] text-[#5c7065] font-semibold"><ShieldCheck size={15}/> Tenant-scoped signals</span></div>
            {/* Account metrics from the backend; no invented demo figures. */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <KPI
                    icon={Sparkles}
                    label="Recommended actions"
                    value={recsGenerated}
                    iconBg="bg-blue-50"
                    color="text-blue-600"
                    sub="AI and rules-based opportunities"
                />
                <KPI
                    icon={AlertTriangle}
                    label="Retention watchlist"
                    value={high}
                    iconBg="bg-red-50"
                    color="text-red-600"
                    sub="prioritize customer health"
                />
                <KPI
                    icon={DollarSign}
                    label="Expansion potential"
                    value={`$${Math.round(total).toLocaleString()}`}
                    iconBg="bg-emerald-50"
                    color="text-emerald-600"
                    sub="modeled opportunity, not booked revenue"
                />
            </div>

            <div className="flex items-center justify-between gap-3 pt-4"><div><p className="text-[10px] uppercase font-extrabold tracking-[.18em] text-[#8b988e]">Signal intelligence</p><h2 className="text-[19px] font-extrabold text-[#25332a] mt-1">Understand your portfolio</h2></div><Link to="/chat" className="text-[12px] font-bold text-[#4a7743] flex gap-1 items-center hover:underline">Investigate with AI <ArrowUpRight size={14}/></Link></div>
            {/* Charts: churn risk split + which products customers are on + industry breakdown */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <Card className="p-5">
                    <div className="flex items-center gap-2 mb-3">
                        <PieChartIcon size={15} className="text-gray-400" />
                        <h3 className="text-[14px] font-bold text-gray-900">
                            Churn risk breakdown
                        </h3>
                    </div>
                    {churnPieData.length ? (
                        <ResponsiveContainer width="100%" height={240}>
                            <PieChart>
                                <Pie
                                    data={churnPieData}
                                    dataKey="value"
                                    nameKey="name"
                                    cx="50%"
                                    cy="50%"
                                    innerRadius={55}
                                    outerRadius={85}
                                    paddingAngle={2}
                                >
                                    {churnPieData.map((entry) => (
                                        <Cell
                                            key={entry.name}
                                            fill={
                                                CHURN_COLORS[entry.name] ||
                                                "#94a3b8"
                                            }
                                        />
                                    ))}
                                </Pie>
                                <Tooltip
                                    formatter={(v, n) => [
                                        `${v} customer${v === 1 ? "" : "s"}`,
                                        n,
                                    ]}
                                    contentStyle={{
                                        borderRadius: 10,
                                        border: "1px solid #e2e8f0",
                                        fontSize: 12,
                                        boxShadow:
                                            "0 4px 6px -1px rgb(0 0 0 / 0.05)",
                                    }}
                                />
                                <Legend
                                    verticalAlign="bottom"
                                    height={28}
                                    iconType="circle"
                                    wrapperStyle={{ fontSize: 12 }}
                                />
                            </PieChart>
                        </ResponsiveContainer>
                    ) : (
                        <div className="h-[240px] flex items-center justify-center text-[13px] text-gray-400">
                            No churn data yet.
                        </div>
                    )}
                </Card>

                <Card className="p-5">
                    <div className="flex items-center justify-between gap-2 mb-3">
                        <div className="flex items-center gap-2">
                            <BarChart3 size={15} className="text-gray-400" />
                            <h3 className="text-[14px] font-bold text-gray-900">
                                Products in use
                            </h3>
                            <span className="text-[11px] text-gray-400 font-medium">
                                {allProductsData.length} total
                            </span>
                        </div>
                        {allProductsData.length > 6 && (
                            <button
                                onClick={() => setShowAllProducts((v) => !v)}
                                className="text-[11px] font-semibold text-violet-600 hover:text-violet-700 transition-colors"
                            >
                                {showAllProducts
                                    ? "Show less"
                                    : `Show all (${allProductsData.length})`}
                            </button>
                        )}
                    </div>
                    {topProductsData.length ? (
                        <ResponsiveContainer
                            width="100%"
                            height={Math.max(
                                240,
                                topProductsData.length * 34 + 20,
                            )}
                        >
                            <BarChart
                                data={topProductsData}
                                layout="vertical"
                                margin={{ left: 8, right: 16 }}
                            >
                                <CartesianGrid
                                    strokeDasharray="3 3"
                                    stroke="#f1f5f9"
                                    horizontal={false}
                                />
                                <XAxis
                                    type="number"
                                    allowDecimals={false}
                                    tick={{ fontSize: 11, fill: "#94a3b8" }}
                                    axisLine={false}
                                    tickLine={false}
                                />
                                <YAxis
                                    type="category"
                                    dataKey="name"
                                    width={120}
                                    tick={{ fontSize: 11, fill: "#64748b" }}
                                    axisLine={false}
                                    tickLine={false}
                                />
                                <Tooltip
                                    content={
                                        <ProductTooltip
                                            catalogIndex={catalogIndex}
                                        />
                                    }
                                />
                                <Bar
                                    dataKey="count"
                                    fill="#6366f1"
                                    radius={[0, 4, 4, 0]}
                                    barSize={16}
                                />
                            </BarChart>
                        </ResponsiveContainer>
                    ) : (
                        <div className="h-[240px] flex items-center justify-center text-[13px] text-gray-400">
                            No product data yet.
                        </div>
                    )}
                </Card>

                <Card className="p-5">
                    <div className="flex items-center gap-2 mb-3">
                        <PieChartIcon size={15} className="text-gray-400" />
                        <h3 className="text-[14px] font-bold text-gray-900">
                            Industry breakdown
                        </h3>
                    </div>
                    {topIndustriesData.length ? (
                        <ResponsiveContainer width="100%" height={240}>
                            <BarChart
                                data={topIndustriesData}
                                layout="vertical"
                                margin={{ left: 8, right: 16 }}
                            >
                                <CartesianGrid
                                    strokeDasharray="3 3"
                                    stroke="#f1f5f9"
                                    horizontal={false}
                                />
                                <XAxis
                                    type="number"
                                    allowDecimals={false}
                                    tick={{ fontSize: 11, fill: "#94a3b8" }}
                                    axisLine={false}
                                    tickLine={false}
                                />
                                <YAxis
                                    type="category"
                                    dataKey="name"
                                    width={90}
                                    tick={{ fontSize: 11, fill: "#64748b" }}
                                    axisLine={false}
                                    tickLine={false}
                                />
                                <Tooltip
                                    formatter={(v) => [
                                        `${v} customer${v === 1 ? "" : "s"}`,
                                        "Customers",
                                    ]}
                                    contentStyle={{
                                        borderRadius: 10,
                                        border: "1px solid #e2e8f0",
                                        fontSize: 12,
                                        boxShadow:
                                            "0 4px 6px -1px rgb(0 0 0 / 0.05)",
                                    }}
                                />
                                <Bar
                                    dataKey="count"
                                    fill="#14b8a6"
                                    radius={[0, 4, 4, 0]}
                                    barSize={16}
                                />
                            </BarChart>
                        </ResponsiveContainer>
                    ) : (
                        <div className="h-[240px] flex items-center justify-center text-[13px] text-gray-400">
                            No industry data yet.
                        </div>
                    )}
                </Card>
            </div>

            {/* Top confident opportunities */}
            <Card>
                <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between">
                    <h3 className="text-[14px] font-bold text-gray-900">
                        Prioritized expansion opportunities
                    </h3>
                    <Link
                        to="/customers"
                        className="text-[12px] font-semibold text-blue-600 hover:text-blue-700 inline-flex items-center gap-1"
                    >
                        See all <ChevronRight size={13} />
                    </Link>
                </div>
                {topOpps.length ? (
                    <ul className="divide-y divide-gray-50">
                        {topOpps.map((c) => (
                            <li key={c.customer_id}>
                                <Link
                                    to={`/customers/${c.customer_id}`}
                                    className="flex items-center justify-between gap-4 px-5 py-3 hover:bg-gray-50/50 transition-colors"
                                >
                                    <div className="min-w-0 flex-1">
                                        <p className="text-[13px] font-semibold text-gray-900 truncate">
                                            {c.company_name}
                                        </p>
                                        <p className="text-[12px] text-gray-500 mt-0.5 truncate">
                                            <span className="text-gray-400">
                                                {c.current_product ||
                                                    c.plan_tier}
                                            </span>{" "}
                                            →{" "}
                                            <span className="text-blue-600 font-medium">
                                                {c.recommended_product}
                                            </span>
                                        </p>
                                    </div>
                                    {c.total_opportunity > 0 && (
                                        <span className="text-[12px] font-semibold text-gray-600 tabular-nums shrink-0">
                                            $
                                            {Math.round(
                                                c.total_opportunity,
                                            ).toLocaleString()}
                                        </span>
                                    )}
                                    <div className="shrink-0">
                                        <Confidence value={c.confidence} />
                                    </div>
                                </Link>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <div className="px-5 py-10 text-center text-[13px] text-gray-400">
                        No strong opportunities yet — analyze more customers.
                    </div>
                )}
            </Card>

            {/* Accounts we couldn't recommend anything for -- what to do instead */}
            {noRecCustomers.length > 0 && (
                <Card>
                    <div className="px-5 py-3.5 border-b border-gray-100 flex items-center gap-2">
                        <Sparkles size={14} className="text-indigo-500" />
                        <h3 className="text-[14px] font-bold text-gray-900">
                            No upsell — here's what to do instead
                        </h3>
                        <span className="text-[11px] text-gray-400">
                            ({noRecCustomers.length})
                        </span>
                    </div>
                    <ul className="divide-y divide-gray-50">
                        {noRecCustomers.map((c) => {
                            const meta =
                                RETENTION_ACTION_META[
                                    c.retention_action_type
                                ] || RETENTION_ACTION_META.account_review;
                            const ActionIcon = meta.icon;
                            return (
                                <li
                                    key={c.customer_id}
                                    className="px-5 py-3 flex items-start justify-between gap-4"
                                >
                                    <div className="min-w-0 flex items-start gap-3">
                                        <div
                                            className={`shrink-0 mt-0.5 w-7 h-7 rounded-full flex items-center justify-center ring-1 ring-inset ${meta.className}`}
                                        >
                                            <ActionIcon size={14} />
                                        </div>
                                        <div className="min-w-0">
                                            <p className="text-[13px] font-semibold text-gray-900">
                                                {c.company_name}
                                            </p>
                                            {c.no_recommendation_reason && (
                                                <p className="text-[12px] text-gray-700 mt-0.5">
                                                    <span className="font-semibold text-gray-500">
                                                        Why:{" "}
                                                    </span>
                                                    {c.no_recommendation_reason}
                                                </p>
                                            )}
                                            <p className="text-[12px] text-gray-500 mt-0.5">
                                                {c.retention_action}
                                            </p>
                                        </div>
                                    </div>
                                    <div className="shrink-0 flex flex-col items-end gap-1">
                                        {c.churn_segment && (
                                            <span
                                                className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ring-1 ring-inset ${
                                                    c.churn_segment === "HIGH"
                                                        ? "bg-red-100 text-red-700 ring-red-500/20"
                                                        : c.churn_segment ===
                                                            "MEDIUM"
                                                          ? "bg-amber-100 text-amber-700 ring-amber-500/20"
                                                          : "bg-emerald-100 text-emerald-700 ring-emerald-500/20"
                                                }`}
                                            >
                                                {c.churn_segment}
                                            </span>
                                        )}
                                    </div>
                                </li>
                            );
                        })}
                    </ul>
                </Card>
            )}
            <FutureWorkModal
                customer={emailFor}
                onClose={() => setEmailFor(null)}
            />
        </div>
    );
}
