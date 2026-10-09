import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search,
  Package,
  Info,
  Users,
  DollarSign,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Loader2,
  Tag,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
  Trash2,
  Edit2,
  Plus,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { getCatalog, addCatalogProduct, deleteCatalogProduct, updateCatalogProduct } from "../api/client";

function ProductModal({ initialData, onClose, onSave }) {
  const [form, setForm] = useState({
    product_name: initialData?.product_name || '',
    category: initialData?.category || '',
    tier_level: initialData?.tier_level || 1,
    price_per_seat: initialData?.price_per_seat || 0,
    description: initialData?.description || ''
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!form.product_name) return setError('Product name is required')
    setLoading(true); setError('')
    try {
      if (initialData?.product_id) await updateCatalogProduct(initialData.product_id, form)
      else await addCatalogProduct(form)
      onSave()
    } catch(err) {
      setError(err.response?.data?.detail || 'Failed to save product')
    } finally { setLoading(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/50 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm overflow-hidden" onClick={e=>e.stopPropagation()}>
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="font-bold text-gray-900">{initialData ? 'Edit' : 'Add'} Custom Product</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700"><X size={16}/></button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Product Name</label>
            <input value={form.product_name} onChange={e=>setForm({...form, product_name: e.target.value})} className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Category</label>
              <input value={form.category} onChange={e=>setForm({...form, category: e.target.value})} className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Tier</label>
              <input type="number" value={form.tier_level} onChange={e=>setForm({...form, tier_level: parseInt(e.target.value)})} className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Price / Seat ($)</label>
            <input type="number" step="0.01" value={form.price_per_seat} onChange={e=>setForm({...form, price_per_seat: parseFloat(e.target.value)})} className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Description</label>
            <textarea value={form.description} onChange={e=>setForm({...form, description: e.target.value})} rows={2} className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
          </div>
          {error && <p className="text-sm text-red-600 bg-red-50 p-2 rounded-lg">{error}</p>}
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="flex-1 py-2 text-sm font-semibold text-gray-600 bg-gray-50 hover:bg-gray-100 rounded-xl transition-colors">Cancel</button>
            <button type="submit" disabled={loading} className="flex-1 py-2 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-xl transition-colors flex items-center justify-center gap-2">
              {loading ? <Loader2 size={14} className="animate-spin"/> : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

/**
 * Renders this tenant's real product catalog (GET /api/catalog), grouped
 * by whatever `category` value actually exists in their data -- no fixed
 * Upgrades/Add-ons/Complementary/Retention taxonomy, since that only ever
 * made sense for a SaaS-shaped tenant. A tenant with no `category` column
 * at all falls back to a single "All Products" group instead of forcing
 * one. Eligible-customer counts and revenue potential are computed
 * server-side against this tenant's real customers, not approximated here.
 */
export default function UpsellCatalog({ collapsed: initialCollapsed = true }) {
  const [products, setProducts] = useState([]);
  const [isDemoSeed, setIsDemoSeed] = useState(false);
  const [revenueModel, setRevenueModel] = useState("recurring");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState(null);
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const navigate = useNavigate();

  const loadCatalog = () => {
    setLoading(true);
    getCatalog()
      .then((r) => {
        setProducts(r.products || []);
        setIsDemoSeed(!!r.is_demo_seed);
        setRevenueModel(r.revenue_model || "recurring");
      })
      .catch(() => setError("Could not load the product catalog."))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadCatalog(); }, []);

  const handleDelete = async (id) => {
    if (!confirm('Are you sure you want to delete this product?')) return;
    try {
      await deleteCatalogProduct(id);
      loadCatalog();
    } catch(err) {
      alert(err.response?.data?.detail || 'Failed to delete');
    }
  };

  // "recurring" tenants (SaaS) get "/mo potential" -- a valid recurring
  // figure. "one_time" tenants (retail/goods) get just "potential", since
  // labeling a one-off sale total as monthly recurring revenue would be
  // fabricating a number that doesn't exist.
  const revenueSuffix = revenueModel === "one_time" ? "" : "/mo";

  const categories = useMemo(() => {
    const seen = new Set();
    const list = [];
    for (const p of products) {
      const name = p.category || "All Products";
      if (!seen.has(name)) {
        seen.add(name);
        list.push(name);
      }
    }
    return list;
  }, [products]);

  useEffect(() => {
    if (!activeTab && categories.length > 0) setActiveTab(categories[0]);
  }, [categories, activeTab]);

  const filteredItems = useMemo(() => {
    if (!search) return products;
    const q = search.toLowerCase();
    return products.filter(
      (p) =>
        (p.product_name || "").toLowerCase().includes(q) ||
        (p.category || "").toLowerCase().includes(q),
    );
  }, [products, search]);

  const currentItems = filteredItems.filter(
    (p) => (p.category || "All Products") === activeTab,
  );

  // For collapsed preview: top item (by eligible seats) from each category
  const previewItems = categories
    .map((cat) => {
      const items = filteredItems.filter(
        (p) => (p.category || "All Products") === cat,
      );
      return [...items].sort(
        (a, b) => (b.eligible_seats || 0) - (a.eligible_seats || 0),
      )[0];
    })
    .filter(Boolean);

  const totalSeats = products.reduce(
    (sum, p) => sum + (p.eligible_seats || 0),
    0,
  );
  const totalRevenue = products.reduce(
    (sum, p) => sum + (p.potential_revenue || 0),
    0,
  );

  const handleEligibleClick = (item) => {
    navigate(`/customers?offer=${encodeURIComponent(item.product_id)}`);
  };

  if (loading) {
    return (
      <div className="bg-white rounded-2xl border border-gray-200/60 shadow-card overflow-hidden mt-6 p-8 flex items-center justify-center gap-2 text-gray-400">
        <Loader2 size={16} className="animate-spin" />{" "}
        <span className="text-[13px]">Loading catalog…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white rounded-2xl border border-gray-200/60 shadow-card overflow-hidden mt-6 p-8 text-center">
        <p className="text-[13px] text-gray-500">{error}</p>
      </div>
    );
  }

  if (products.length === 0) {
    return (
      <div className="bg-white rounded-2xl border border-gray-200/60 shadow-card overflow-hidden mt-6 p-8 text-center">
        <Package size={28} className="text-gray-300 mx-auto mb-2" />
        <p className="text-[13px] font-semibold text-gray-600">
          No product catalog uploaded yet
        </p>
        <p className="text-[12px] text-gray-400 mt-1">
          Upload a product catalog to see it here, with live eligibility and
          revenue potential per product.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200/60 shadow-card overflow-hidden mt-6">
      {/* Header */}
      <div className="px-6 py-5 border-b border-gray-100">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-xl bg-blue-50 flex items-center justify-center">
              <Package size={18} className="text-blue-600" />
            </div>
            <div>
              <h2 className="text-[15px] font-bold text-gray-900 tracking-tight">
                Product Catalog
              </h2>
              <p className="text-[12px] text-gray-500 mt-0.5">
                {isDemoSeed
                  ? "Demo seed data — click eligible count to filter customers"
                  : "Sales enablement reference — click eligible count to filter customers"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <button onClick={() => setShowAddModal(true)} className="flex items-center gap-1.5 text-[12px] font-semibold text-blue-600 hover:text-blue-700 transition-colors px-3 py-1.5 rounded-xl bg-blue-50 hover:bg-blue-100">
              <Plus size={14} /> Add Product
            </button>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5 text-[12px] font-semibold text-gray-600 bg-gray-50 border border-gray-200 px-3 py-1.5 rounded-xl">
                <Users size={13} className="text-blue-500" />
                {totalSeats.toLocaleString()} seats in scope
              </div>
              {totalRevenue > 0 && (
                <div className="flex items-center gap-1.5 text-[12px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 px-3 py-1.5 rounded-xl">
                  <DollarSign size={13} />$
                  {Math.round(totalRevenue).toLocaleString("en-US")}
                  {revenueSuffix} potential
                </div>
              )}
            </div>
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="flex items-center gap-1.5 text-[12px] font-semibold text-gray-500 hover:text-blue-600 transition-colors px-3 py-1.5 rounded-xl hover:bg-gray-50"
            >
              {collapsed ? (
                <>
                  <ChevronDown size={14} /> View full catalog
                </>
              ) : (
                <>
                  <ChevronUp size={14} /> Collapse
                </>
              )}
            </button>
          </div>
        </div>

        {/* Tabs — only in expanded mode. Categories are whatever this
            tenant's data actually contains. */}
        {!collapsed && (
          <>
            <div className="flex gap-2 mt-5 overflow-x-auto pb-1">
              {categories.map((cat) => {
                const count = filteredItems.filter(
                  (p) => (p.category || "All Products") === cat,
                ).length;
                const active = activeTab === cat;
                return (
                  <button
                    key={cat}
                    onClick={() => setActiveTab(cat)}
                    className={`flex items-center gap-2 px-4 py-2 rounded-xl text-[13px] font-semibold transition-all whitespace-nowrap ${
                      active
                        ? "bg-blue-600 text-white shadow-sm shadow-blue-500/20"
                        : "bg-gray-50 text-gray-600 hover:bg-gray-100"
                    }`}
                  >
                    <Tag size={14} />
                    {cat}
                    <span
                      className={`text-[11px] px-1.5 py-0.5 rounded-md ${active ? "bg-blue-500 text-white" : "bg-gray-200 text-gray-500"}`}
                    >
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="mt-4 relative">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
              />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search catalog…"
                className="w-full md:w-72 pl-9 pr-3 py-2 rounded-xl bg-gray-50 border border-gray-200 text-[13px] placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-300 transition-all"
              />
            </div>
          </>
        )}
      </div>

      {/* Content */}
      <div className="p-5 bg-gray-50/30">
        <AnimatePresence mode="popLayout">
          {collapsed ? (
            /* Compact preview: top item per category */
            <motion.div
              key="collapsed"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3"
            >
              {previewItems.map((item) => (
                <div
                  key={item.product_id}
                  className="bg-white border border-gray-200/70 rounded-xl p-4 hover:border-blue-200 hover:shadow-sm transition-all"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <div className="h-7 w-7 rounded-lg bg-blue-50 flex items-center justify-center">
                      <Tag size={14} className="text-blue-600" />
                    </div>
                    <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wide truncate">
                      {item.category || "All Products"}
                    </span>
                    {item.is_fallback_pool && (
                      <span
                        title="No existing customers in this category yet — showing the full customer base instead of a category-scoped match."
                        className="text-[9px] font-bold text-amber-600 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded-md ml-auto shrink-0"
                      >
                        FULL BASE
                      </span>
                    )}
                  </div>
                  <p className="text-[13px] font-bold text-gray-900 mb-3 leading-snug">
                    {item.product_name}
                  </p>
                  <button
                    onClick={() => handleEligibleClick(item)}
                    className="flex items-center gap-1.5 text-blue-600 hover:text-blue-700 transition-colors group"
                  >
                    <span className="text-[20px] font-black tabular-nums">
                      {(item.eligible_customers || 0).toLocaleString()}
                    </span>
                    <span className="text-[11px] font-semibold text-gray-500 group-hover:text-blue-600">
                      accounts eligible{" "}
                      <ExternalLink size={10} className="inline" />
                    </span>
                  </button>
                  <p className="text-[10px] text-gray-400 mt-0.5">
                    {(item.eligible_seats || 0).toLocaleString()} seats
                  </p>
                  {item.potential_revenue > 0 && (
                    <p className="text-[11px] text-emerald-600 font-semibold mt-1">
                      $
                      {Math.round(item.potential_revenue).toLocaleString(
                        "en-US",
                      )}
                      {revenueSuffix} potential
                    </p>
                  )}
                </div>
              ))}
            </motion.div>
          ) : (
            /* Full expanded view */
            <motion.div
              key="expanded"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              {currentItems.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {currentItems.map((item) => (
                    <motion.div
                      key={item.product_id}
                      layout
                      initial={{ opacity: 0, scale: 0.97 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      className="bg-white border border-gray-200/70 rounded-xl p-4 hover:border-blue-200 hover:shadow-md transition-all group flex flex-col"
                    >
                      <div className="flex items-start justify-between gap-2 mb-3">
                        <div className="flex items-center gap-2">
                          <div className="h-7 w-7 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
                            <Tag size={14} className="text-blue-600" />
                          </div>
                          <h3 className="text-[13px] font-bold text-gray-900 group-hover:text-blue-600 transition-colors leading-snug">
                            {item.product_name}
                          </h3>
                        </div>
                        <div className="flex items-center gap-1">
                          {item.source === 'custom' && (
                            <button onClick={(e) => { e.stopPropagation(); setEditingItem(item); }} className="p-1 text-gray-400 hover:text-blue-600 transition-colors"><Edit2 size={13}/></button>
                          )}
                          {item.source === 'custom' && (
                            <button onClick={(e) => { e.stopPropagation(); handleDelete(item.product_id); }} className="p-1 text-gray-400 hover:text-red-600 transition-colors"><Trash2 size={13}/></button>
                          )}
                          <span className="text-[11px] text-gray-400 font-medium shrink-0 ml-1">
                            ${item.price_per_seat.toLocaleString("en-US")}
                          </span>
                        </div>
                      </div>

                      <p className="text-[12px] text-gray-500 leading-relaxed mb-2 flex-1">
                        Tier {item.tier_level}
                        {item.category ? ` · ${item.category}` : ""}
                      </p>

                      {item.is_fallback_pool && (
                        <p
                          title="No existing customers in this category yet — showing the full customer base instead of a category-scoped match."
                          className="text-[10px] font-bold text-amber-600 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded-md inline-block mb-2 w-fit"
                        >
                          FULL BASE, NOT CATEGORY-MATCHED
                        </p>
                      )}

                      <div className="flex items-end justify-between mb-3">
                        <div>
                          <button
                            onClick={() => handleEligibleClick(item)}
                            className="flex items-center gap-1.5 hover:text-blue-700 transition-colors group/btn"
                          >
                            <span className="text-[24px] font-black text-blue-600 tabular-nums">
                              {(item.eligible_customers || 0).toLocaleString()}
                            </span>
                            <div className="ml-1">
                              <p className="text-[10px] font-bold text-gray-500 group-hover/btn:text-blue-600 uppercase tracking-wide">
                                accounts eligible
                              </p>
                              <p className="text-[10px] text-gray-400">
                                {(item.eligible_seats || 0).toLocaleString()} seats
                              </p>
                              <p className="text-[10px] text-blue-500 flex items-center gap-0.5">
                                Filter customers <ExternalLink size={9} />
                              </p>
                            </div>
                          </button>
                        </div>
                        {item.potential_revenue > 0 && (
                          <div className="text-right">
                            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                              Potential
                            </p>
                            <p className="text-[14px] font-bold text-emerald-600 tabular-nums">
                              $
                              {Math.round(item.potential_revenue).toLocaleString(
                                "en-US",
                              )}
                              {revenueSuffix}
                            </p>
                          </div>
                        )}
                      </div>
                    </motion.div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-12">
                  <Info size={32} className="text-gray-300 mx-auto mb-3" />
                  <p className="text-[14px] font-semibold text-gray-600">
                    No products found{activeTab ? ` in ${activeTab}` : ""}
                  </p>
                  <p className="text-[12px] text-gray-400 mt-1">
                    Try adjusting your search.
                  </p>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      {(showAddModal || editingItem) && (
        <ProductModal 
          initialData={editingItem} 
          onClose={() => { setShowAddModal(false); setEditingItem(null); }}
          onSave={() => { setShowAddModal(false); setEditingItem(null); loadCatalog(); }} 
        />
      )}
    </div>
  );
}