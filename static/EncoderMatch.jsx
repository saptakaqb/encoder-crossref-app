// ── Security hooks ─────────────────────────────────────────────────────────
const IDLE_TIMEOUT_MS = 10 * 60 * 1000;  // 10 minutes

function useIdleTimeout(onLogout) {
  React.useEffect(() => {
    let timer = setTimeout(onLogout, IDLE_TIMEOUT_MS);
    const reset = () => { clearTimeout(timer); timer = setTimeout(onLogout, IDLE_TIMEOUT_MS); };
    const events = ['mousemove','keydown','click','touchstart'];
    events.forEach(e => window.addEventListener(e, reset));
    return () => { clearTimeout(timer); events.forEach(e => window.removeEventListener(e, reset)); };
  }, [onLogout]);
}

function useSessionGuard(authToken, onLogout) {
  // Polls /api/auth/me every 30s. If server returns 401 (session superseded),
  // forces logout with a message. No S3 or extra infrastructure needed.
  React.useEffect(() => {
    if (!authToken || API_MODE !== 'live') return;
    const validate = async () => {
      try {
        const resp = await fetch(`${FASTAPI_BASE_URL}/api/auth/me`, {
          headers: { 'Authorization': `Bearer ${authToken}` }
        });
        if (resp.status === 401) {
          const data = await resp.json().catch(() => ({}));
          const msg = (data.detail || '').includes('superseded')
            ? 'You were logged out because your account signed in on another device.'
            : 'Your session has expired. Please log in again.';
          onLogout(msg);
        }
      } catch (_) { /* network error — don't force logout */ }
    };
    validate();
    const interval = setInterval(validate, 30_000);
    return () => clearInterval(interval);
  }, [authToken, onLogout]);
}

// ─────────────────────────────────────────────────────
// EncoderMatch — Full React App
// Consolidated from 9-file Claude Design output
// Claude API wired for AI explanations
// FastAPI-ready with API_MODE toggle
// ─────────────────────────────────────────────────────

// ── FastAPI config (swap to 'live' + real URL when ready) ─────────────────
const API_MODE = 'live';
const FASTAPI_BASE_URL = '';

// ── Real matcher data ──────────────────────────────────────────────────────
const MOCK_DATA = {
  user: {
    name: "Jan Schulz", email: "j.schulz@kuebler.com",
    role: "enduser", client: "Kübler Group",
    searches_used: 53, searches_limit: 100,
    allowed_sources: ["kubler"], allowed_targets: ["epc", "sick"],
    matching_direction: "source_only", admin_email: "admin@kuebler.com",
  },
  source: {
    part_number: "8.KIS40.1342.1024", manufacturer: "Kübler", family: "KIS40",
    shaft_type: "solid", shaft_bore_diameter_mm: 6, ip_rating: 64,
    output_circuit_canonical: "Push-Pull", connection_type_canonical: "M12",
    connector_pins: 8, housing_diameter_mm: 40,
    supply_voltage_min_v: 5, supply_voltage_max_v: 30,
    operating_temp_max_c: 85, sensing_method: "Optical",
    cpr_values: [100, 200, 360, 500, 1000, 1024, 2048, 2500],
    shock_resistance_ms2: 1000, vibration_resistance_ms2: 100,
    shaft_load_radial_n: 40, output_voltage_class: "universal",
  },
  results: [
    {
      rank: 1, part_number: "EPC-802S-07-L-XXXX-A-PP-F-K-5",
      manufacturer: "EPC", manufacturer_full: "Encoder Products Company", family: "802S",
      total_score: 0.938, t2_score: 0.940, t3_score: 0.932,
      product_url: "https://www.encoder.com/model-802s", url_type: "family",
      is_programmable: true, ppr_range_min: 1, ppr_range_max: 30000,
      cpr_covered: [100, 200, 360, 500, 1000, 1024, 2048, 2500], cpr_total: 8,
      t2: {
        cpr_values:                { score: 1.00, src_val: "8 values (100–2500)", cand_val: "1–30,000 (programmable)", label: "PPR Coverage" },
        ip_rating:                 { score: 1.00, src_val: "IP64", cand_val: "IP65", label: "IP Rating" },
        connection_type_canonical: { score: 1.00, src_val: "M12", cand_val: "M12", label: "Connection Type" },
        output_circuit_canonical:  { score: 1.00, src_val: "Push-Pull", cand_val: "Push-Pull", label: "Output Circuit" },
        housing_diameter_mm:       { score: 0.64, src_val: "40 mm", cand_val: "50.8 mm", label: "Housing Diameter" },
        shaft_bore_diameter_mm:    { score: 1.00, src_val: "6 mm", cand_val: "6 mm", label: "Bore Diameter" },
      },
      t3: {
        supply_voltage:           { score: 1.00, src_val: "5–30 V", cand_val: "5–28 V", label: "Supply Voltage" },
        sensing_method:           { score: 1.00, src_val: "Optical", cand_val: "Optical", label: "Sensing Method" },
        operating_temp_max_c:     { score: 1.00, src_val: "85 °C", cand_val: "100 °C", label: "Max Operating Temp" },
        shock_resistance_ms2:     { score: 0.74, src_val: "1,000 m/s²", cand_val: "735 m/s²", label: "Shock Resistance" },
        shaft_load_radial_n:      { score: 1.00, src_val: "40 N", cand_val: "45 N", label: "Radial Shaft Load" },
        vibration_resistance_ms2: { score: 1.00, src_val: "100 m/s²", cand_val: "100 m/s²", label: "Vibration Resistance" },
        connector_pins:           { score: 1.00, src_val: "8 pins", cand_val: "8 pins", label: "Connector Pins" },
      },
    },
    {
      rank: 2, part_number: "EPC-755A-20-S-XXXX-Q-PU-S-C02",
      manufacturer: "EPC", manufacturer_full: "Encoder Products Company", family: "755A",
      total_score: 0.804, t2_score: 0.786, t3_score: 0.845,
      product_url: "https://www.encoder.com/model-755a", url_type: "family",
      is_programmable: false, ppr_range_min: 1, ppr_range_max: 9999,
      cpr_covered: [100, 200, 360, 500, 1000, 1024, 2048, 2500], cpr_total: 8,
      t2: {
        cpr_values:                { score: 1.00, src_val: "8 values (100–2500)", cand_val: "1–9,999 (any integer)", label: "PPR Coverage" },
        ip_rating:                 { score: 0.00, src_val: "IP64", cand_val: "IP50", label: "IP Rating" },
        connection_type_canonical: { score: 0.50, src_val: "M12", cand_val: "M23", label: "Connection Type" },
        output_circuit_canonical:  { score: 1.00, src_val: "Push-Pull", cand_val: "Push-Pull", label: "Output Circuit" },
        housing_diameter_mm:       { score: 1.00, src_val: "40 mm", cand_val: "38.1 mm", label: "Housing Diameter" },
        shaft_bore_diameter_mm:    { score: 1.00, src_val: "6 mm", cand_val: "6.35 mm", label: "Bore Diameter" },
      },
      t3: {
        supply_voltage:           { score: 1.00, src_val: "5–30 V", cand_val: "4.5–26 V", label: "Supply Voltage" },
        sensing_method:           { score: 1.00, src_val: "Optical", cand_val: "Optical", label: "Sensing Method" },
        operating_temp_max_c:     { score: 1.00, src_val: "85 °C", cand_val: "100 °C", label: "Max Operating Temp" },
        shock_resistance_ms2:     { score: 0.49, src_val: "1,000 m/s²", cand_val: "490 m/s²", label: "Shock Resistance" },
        shaft_load_radial_n:      { score: 0.56, src_val: "40 N", cand_val: "22 N", label: "Radial Shaft Load" },
        vibration_resistance_ms2: { score: 1.00, src_val: "100 m/s²", cand_val: "98 m/s²", label: "Vibration Resistance" },
        connector_pins:           { score: 0.80, src_val: "8 pins", cand_val: "10 pins", label: "Connector Pins" },
      },
    },
    {
      rank: 3, part_number: "EPC-15S-19-S-XXXX-A-PP-M9-K00-S1",
      manufacturer: "EPC", manufacturer_full: "Encoder Products Company", family: "15S",
      total_score: 0.802, t2_score: 0.795, t3_score: 0.820,
      product_url: "https://www.encoder.com/model-15s", url_type: "family",
      is_programmable: false, ppr_range_min: 1, ppr_range_max: 8192,
      cpr_covered: [100, 200, 360, 500, 1000, 1024, 2048], cpr_total: 8,
      t2: {
        cpr_values:                { score: 0.875, src_val: "8 values (100–2500)", cand_val: "1–8,192 (any integer)", label: "PPR Coverage" },
        ip_rating:                 { score: 1.00, src_val: "IP64", cand_val: "IP65", label: "IP Rating" },
        connection_type_canonical: { score: 1.00, src_val: "M12", cand_val: "M12", label: "Connection Type" },
        output_circuit_canonical:  { score: 1.00, src_val: "Push-Pull", cand_val: "Push-Pull", label: "Output Circuit" },
        housing_diameter_mm:       { score: 0.92, src_val: "40 mm", cand_val: "38.1 mm", label: "Housing Diameter" },
        shaft_bore_diameter_mm:    { score: 0.90, src_val: "6 mm", cand_val: "6.35 mm", label: "Bore Diameter" },
      },
      t3: {
        supply_voltage:           { score: 0.90, src_val: "5–30 V", cand_val: "5–26 V", label: "Supply Voltage" },
        sensing_method:           { score: 1.00, src_val: "Optical", cand_val: "Optical", label: "Sensing Method" },
        operating_temp_max_c:     { score: 1.00, src_val: "85 °C", cand_val: "85 °C", label: "Max Operating Temp" },
        shock_resistance_ms2:     { score: 0.50, src_val: "1,000 m/s²", cand_val: "500 m/s²", label: "Shock Resistance" },
        shaft_load_radial_n:      { score: 0.70, src_val: "40 N", cand_val: "28 N", label: "Radial Shaft Load" },
        vibration_resistance_ms2: { score: 0.75, src_val: "100 m/s²", cand_val: "75 m/s²", label: "Vibration Resistance" },
        connector_pins:           { score: 1.00, src_val: "8 pins", cand_val: "8 pins", label: "Connector Pins" },
      },
    },
  ],
  history: [
    { id:1, ts:"2026-05-11 14:32", src_part:"8.KIS40.1342.1024",  targets:["EPC"],         top_match:"EPC-802S",          top_score:0.938, n:53 },
    { id:2, ts:"2026-05-11 11:15", src_part:"8.K58I.5534.1024",   targets:["EPC","Sick"],  top_match:"DFS60E-S4EA01024",  top_score:0.872, n:52 },
    { id:3, ts:"2026-05-10 16:44", src_part:"8.KIS40.1271.0500",  targets:["EPC"],         top_match:"EPC-802S",          top_score:0.901, n:51 },
    { id:4, ts:"2026-05-10 09:20", src_part:"8.K58I.5534.0360",   targets:["Sick"],        top_match:"DFS60B-S4EA00360",  top_score:0.845, n:50 },
    { id:5, ts:"2026-05-09 15:02", src_part:"8.KIS40.1342.2048",  targets:["EPC","Sick"],  top_match:"EPC-755A",          top_score:0.821, n:49 },
    { id:6, ts:"2026-05-09 11:30", src_part:"8.K80I.3311.1024",   targets:["EPC"],         top_match:"EPC-802S",          top_score:0.796, n:48 },
    { id:7, ts:"2026-05-08 14:18", src_part:"8.KIH40.4422.1000",  targets:["EPC","Sick"],  top_match:"DFS60E-BEAN01024",  top_score:0.758, n:47 },
    { id:8, ts:"2026-05-08 09:05", src_part:"8.KIS40.1271.2500",  targets:["EPC"],         top_match:"EPC-15S",           top_score:0.811, n:46 },
  ],
  adminUsers: [
    { id:1, name:"Jan Schulz",   email:"j.schulz@kuebler.com",   used:53,  limit:100, dbs:["epc","sick"],          dir:"source_only",   status:"active",  last:"Today" },
    { id:2, name:"Marie Fischer",email:"m.fischer@kuebler.com",  used:88,  limit:100, dbs:["epc","sick"],          dir:"source_only",   status:"active",  last:"Today" },
    { id:3, name:"Klaus Bauer",  email:"k.bauer@kuebler.com",    used:100, limit:100, dbs:["epc"],                 dir:"source_only",   status:"locked",  last:"Yesterday" },
    { id:4, name:"Petra Müller", email:"p.mueller@kuebler.com",  used:12,  limit:50,  dbs:["epc","sick"],          dir:"bidirectional", status:"active",  last:"3 days ago" },
    { id:5, name:"Dieter Lang",  email:"d.lang@kuebler.com",     used:0,   limit:100, dbs:["epc","sick","baumer"], dir:"bidirectional", status:"invited", last:"Never" },
    { id:6, name:"Anna Weber",   email:"a.weber@kuebler.com",    used:34,  limit:75,  dbs:["epc"],                 dir:"source_only",   status:"active",  last:"2 days ago" },
  ],
  clients: [
    { id:1, name:"Kübler Group",    slug:"kuebler", users:6, active:5, searches_month:340, limit:600, status:"active",  since:"Jan 2026", dbs:["epc","sick","baumer"] },
    { id:2, name:"EPC",             slug:"epc",     users:3, active:2, searches_month:122, limit:300, status:"active",  since:"Feb 2026", dbs:["kubler","sick","baumer"] },
    { id:3, name:"Sick AG",         slug:"sick",    users:0, active:0, searches_month:0,   limit:300, status:"pending", since:"—",        dbs:["kubler","epc"] },
    { id:4, name:"Posital / Fraba", slug:"posital", users:0, active:0, searches_month:0,   limit:300, status:"pending", since:"—",        dbs:["kubler","epc","sick"] },
  ],
  availableDbs: ["kubler","epc","sick","baumer","nidec","lika"],
};

const ALL_MANUFACTURERS = ['kubler','epc','sick','posital'];
const MFR_LABELS = { kubler:'Kübler', epc:'EPC', sick:'Sick', posital:'Posital' };

// ── Design tokens ──────────────────────────────────────────────────────────
const T = {
  green:  { bg:'#f0fdf4', text:'#15803d', dot:'#16a34a' },
  amber:  { bg:'#fffbeb', text:'#b45309', dot:'#d97706' },
  orange: { bg:'#fff7ed', text:'#c2410c', dot:'#ea580c' },
  red:    { bg:'#fef2f2', text:'#b91c1c', dot:'#dc2626' },
  gray:   { bg:'#f8fafc', text:'#64748b', dot:'#94a3b8' },
};

function scoreTheme(s) {
  if (s == null) return T.gray;
  if (s >= 0.85) return T.green;
  if (s >= 0.60) return T.amber;
  if (s >= 0.35) return T.orange;
  return T.red;
}

// ── UI Primitives ──────────────────────────────────────────────────────────
function ScoreGauge({ score, size=84, dark=false }) {
  const r=size*0.36, cx=size/2, cy=size/2+size*0.04;
  const theme=scoreTheme(score);
  function pt(a){const rad=((a-90)*Math.PI)/180;return[cx+r*Math.cos(rad),cy+r*Math.sin(rad)];}
  const [sx,sy]=pt(135),[ex,ey]=pt(405);
  const arcLen=(270/360)*2*Math.PI*r, filled=(score??0)*arcLen;
  const trackCol=dark?'#334155':'#e2e8f0', sw=size*0.095;
  const pct=score!=null?(score*100).toFixed(1):'—';
  const label=score!=null?(score>=0.85?'HIGH':score>=0.60?'MED':'LOW'):null;
  return (
    <div style={{display:'flex',flexDirection:'column',alignItems:'center',gap:2}}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{display:'block'}}>
        <path d={`M ${sx} ${sy} A ${r} ${r} 0 1 1 ${ex} ${ey}`} fill="none" stroke={trackCol} strokeWidth={sw} strokeLinecap="round"/>
        {score!=null&&<path d={`M ${sx} ${sy} A ${r} ${r} 0 1 1 ${ex} ${ey}`} fill="none" stroke={theme.dot} strokeWidth={sw} strokeLinecap="round" strokeDasharray={`${filled} ${arcLen-filled}`}/>}
        <text x={cx} y={cy+size*0.075} textAnchor="middle" dominantBaseline="middle" fill={dark?'#f1f5f9':'#111827'} fontSize={size*0.215} fontWeight="700" fontFamily="IBM Plex Sans, sans-serif">{pct}</text>
      </svg>
      {label&&<span style={{fontSize:size*0.1,fontWeight:600,color:theme.dot,letterSpacing:'0.06em',fontFamily:'IBM Plex Sans, sans-serif',lineHeight:1}}>{label}</span>}
    </div>
  );
}

function SubScoreBar({ label, score, dark=false }) {
  const theme=scoreTheme(score), pct=((score??0)*100).toFixed(1);
  return (
    <div style={{display:'flex',alignItems:'center',gap:10,fontSize:12}}>
      <span style={{width:130,color:dark?'#94a3b8':'#64748b',fontWeight:500,flexShrink:0}}>{label}</span>
      <div style={{flex:1,height:5,borderRadius:3,background:dark?'#334155':'#e2e8f0',overflow:'hidden'}}>
        <div style={{width:`${pct}%`,height:'100%',borderRadius:3,background:theme.dot,transition:'width 0.6s ease'}}/>
      </div>
      <span style={{width:36,textAlign:'right',fontWeight:600,color:theme.text,fontVariantNumeric:'tabular-nums'}}>{pct}%</span>
    </div>
  );
}

function ScoreDot({ score }) {
  return <span style={{display:'inline-block',width:8,height:8,borderRadius:'50%',background:scoreTheme(score).dot,flexShrink:0}}/>;
}

function FieldRow({ label, srcVal, candVal, score, srcLabel='', candLabel='', dark=false, unscored=false }) {
  const theme=scoreTheme(score), textCol=dark?'#e2e8f0':'#111827', mutedCol=dark?'#94a3b8':'#64748b';
  const nameCol=dark?'#60a5fa':'#1a3570', monoStyle={fontFamily:'IBM Plex Mono, monospace',fontSize:11.5};
  return (
    <div style={{display:'grid',gridTemplateColumns:'12px 1fr 8px 1fr 52px',alignItems:'start',gap:6,
      padding:'6px 12px',borderRadius:4,fontSize:12,
      borderBottom:`1px solid ${dark?'rgba(255,255,255,0.04)':'rgba(0,0,0,0.04)'}`}}>
      <div style={{paddingTop:3}}><ScoreDot score={unscored?null:score}/></div>
      {/* Source side */}
      <div style={{minWidth:0}}>
        <span style={{fontSize:10.5,fontWeight:600,color:nameCol,display:'block',
          whiteSpace:'normal',wordBreak:'break-word',marginBottom:2}}>
          {srcLabel||label}
        </span>
        <span style={{...monoStyle,color:mutedCol,display:'block',
          whiteSpace:'normal',wordBreak:'break-word'}}>
          {srcVal}
        </span>
      </div>
      {/* Arrow */}
      <svg width={8} height={8} viewBox="0 0 8 8" style={{marginTop:8,flexShrink:0}}>
        <path d="M1 4h6M4 1l3 3-3 3" stroke={mutedCol} strokeWidth="1.2" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
      {/* Candidate side */}
      <div style={{minWidth:0}}>
        <span style={{fontSize:10.5,fontWeight:600,color:nameCol,display:'block',
          whiteSpace:'normal',wordBreak:'break-word',marginBottom:2}}>
          {candLabel||label}
        </span>
        <span style={{...monoStyle,color:textCol,display:'block',
          whiteSpace:'normal',wordBreak:'break-word'}}>
          {candVal}
        </span>
      </div>
      {/* Score */}
      <span style={{textAlign:'right',fontWeight:600,fontSize:11.5,paddingTop:8,
        color:unscored?mutedCol:theme.text,fontVariantNumeric:'tabular-nums'}}>
        {unscored?'—':score!=null?(score*100).toFixed(1)+'%':'n/a'}
      </span>
    </div>
  );
}

function PartNum({ value, size=13, dark=false }) {
  if (!value) return null;
  const parts=value.split('XXXX');
  const base={fontFamily:'IBM Plex Mono, monospace',fontSize:size,color:dark?'#e2e8f0':'#111827',letterSpacing:'0.02em'};
  if (parts.length===1) return <span style={base}>{value}</span>;
  return (
    <span style={base}>
      {parts[0]}
      <span title="PPR value to be specified when ordering" style={{color:dark?'#64748b':'#94a3b8',borderBottom:`1px dashed ${dark?'#475569':'#cbd5e1'}`,cursor:'help',paddingBottom:1}}>XXXX</span>
      {parts[1]}
    </span>
  );
}

function SearchCounter({ used, limit, dark=false }) {
  const rem=limit-used, pct=rem/limit, locked=rem<=0;
  let barColor,labelColor,bgColor,borderColor;
  if (locked) { barColor=dark?'#374151':'#e5e7eb'; labelColor=dark?'#ef4444':'#dc2626'; bgColor=dark?'#1a1a2a':'#fef2f2'; borderColor=dark?'#7f1d1d':'#fecaca'; }
  else if (pct<=0.10) { barColor='#dc2626'; labelColor=dark?'#fca5a5':'#b91c1c'; bgColor=dark?'#1a1010':'#fef2f2'; borderColor=dark?'#7f1d1d':'#fecaca'; }
  else if (pct<=0.20) { barColor='#d97706'; labelColor=dark?'#fcd34d':'#b45309'; bgColor=dark?'#1a1500':'#fffbeb'; borderColor=dark?'#78350f':'#fde68a'; }
  else { barColor='#1855d4'; labelColor=dark?'#93c5fd':'#1e40af'; bgColor=dark?'#0f1a2e':'#eff6ff'; borderColor=dark?'#1e3a5f':'#bfdbfe'; }
  const trackBg=dark?'#334155':'#e2e8f0';
  return (
    <div style={{background:bgColor,border:`1px solid ${borderColor}`,borderRadius:8,padding:'10px 14px'}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:6}}>
        <span style={{fontSize:11,fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:dark?'#64748b':'#94a3b8'}}>Searches</span>
        {locked
          ? <span style={{display:'flex',alignItems:'center',gap:4,fontSize:11.5,fontWeight:700,color:labelColor}}>
              <svg width={12} height={12} viewBox="0 0 12 12" fill="none"><rect x="2" y="5" width="8" height="6" rx="1" fill={labelColor}/><path d="M4 5V3.5a2 2 0 114 0V5" stroke={labelColor} strokeWidth="1.3" fill="none" strokeLinecap="round"/></svg>
              Locked
            </span>
          : <span style={{fontSize:12,fontWeight:700,color:labelColor,fontVariantNumeric:'tabular-nums'}}>{rem} / {limit}</span>
        }
      </div>
      <div style={{height:6,borderRadius:3,background:trackBg,overflow:'hidden',marginBottom:5}}>
        {locked
          ? <div style={{height:'100%',width:'100%',background:`repeating-linear-gradient(45deg,${dark?'#374151':'#e5e7eb'} 0px,${dark?'#374151':'#e5e7eb'} 4px,${dark?'#4b5563':'#d1d5db'} 4px,${dark?'#4b5563':'#d1d5db'} 8px)`}}/>
          : <div style={{width:`${Math.round(pct*100)}%`,height:'100%',borderRadius:3,background:barColor,transition:'width 0.4s ease'}}/>
        }
      </div>
      <div style={{fontSize:11,color:dark?'#64748b':'#94a3b8'}}>{locked?'Limit reached — contact your admin':`${rem} remaining this period`}</div>
    </div>
  );
}

function CPRPanel({ result, sourceCpr, dark=false }) {
  const covered=result.cpr_covered||[], total=result.cpr_total||sourceCpr.length;
  const allGood=covered.length===total, none=covered.length===0, isProg=result.is_programmable;
  const rangeStr=`${result.ppr_range_min?.toLocaleString()}–${result.ppr_range_max?.toLocaleString()}`;
  const bgCol=dark?'#0f1a2e':'#f8fafc', borderCol=dark?'#1e3a5f':'#e0e7ef', labelCol=dark?'#94a3b8':'#64748b', textCol=dark?'#e2e8f0':'#111827';
  return (
    <div style={{background:bgCol,border:`1px solid ${borderCol}`,borderRadius:6,padding:'10px 14px'}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:8}}>
        <span style={{fontSize:11,fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:labelCol}}>PPR Coverage</span>
        <span style={{fontSize:11.5,fontWeight:700,color:allGood?T.green.dot:none?T.red.dot:T.amber.dot,display:'flex',alignItems:'center',gap:4}}>
          {none?'⚠ No match':`${covered.length}/${total} covered`}{allGood&&' ✓'}
        </span>
      </div>
      <div style={{display:'flex',flexWrap:'wrap',gap:4,marginBottom:6}}>
        {sourceCpr.map(v=>{
          const hit=covered.includes(v);
          return <span key={v} style={{fontSize:11,padding:'2px 6px',borderRadius:3,fontFamily:'IBM Plex Mono, monospace',background:hit?(dark?'#14532d':'#dcfce7'):(dark?'#450a0a':'#fee2e2'),color:hit?T.green.dot:T.red.dot,border:`1px solid ${hit?(dark?'#166534':'#bbf7d0'):(dark?'#7f1d1d':'#fecaca')}`}}>{v.toLocaleString()}</span>;
        })}
      </div>
      <div style={{fontSize:11,color:labelCol}}>
        Candidate range: <span style={{fontFamily:'IBM Plex Mono, monospace',color:textCol}}>{rangeStr}</span>
        {isProg&&<span style={{marginLeft:6,background:dark?'#1e3a5f':'#eff6ff',color:dark?'#93c5fd':'#1d4ed8',padding:'1px 5px',borderRadius:3,fontSize:10.5,fontWeight:600}}>programmable</span>}
      </div>
      {none&&<div style={{marginTop:8,padding:'6px 10px',borderRadius:4,background:dark?'#450a0a':'#fef2f2',border:`1px solid ${dark?'#7f1d1d':'#fecaca'}`,fontSize:11.5,color:T.red.text,lineHeight:1.5}}>No standard PPR match found — consider a programmable variant</div>}
    </div>
  );
}

function TierDivider({ label, score, dark=false }) {
  const col=dark?'#334155':'#e2e8f0', textCol=dark?'#64748b':'#94a3b8';
  return (
    <div style={{display:'flex',alignItems:'center',gap:8,margin:'8px 12px 4px'}}>
      <span style={{fontSize:10.5,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.08em',color:textCol}}>{label}</span>
      <div style={{flex:1,height:1,background:col}}/>
      <span style={{fontSize:11,fontWeight:600,color:scoreTheme(score).text}}>{score!=null?(score*100).toFixed(1):'n/a'}%</span>
    </div>
  );
}

function LoadingSpinner({ part, dark=false }) {
  return (
    <div style={{display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',padding:'80px 0',gap:20}}>
      <div style={{width:40,height:40,border:`3px solid ${dark?'#334155':'#e2e8f0'}`,borderTopColor:'#1855d4',borderRadius:'50%',animation:'spin 0.8s linear infinite'}}/>
      <div style={{textAlign:'center'}}>
        <div style={{fontSize:14,fontWeight:600,color:dark?'#e2e8f0':'#111827',marginBottom:4}}>Matching {part}</div>
        <div style={{fontSize:12.5,color:dark?'#64748b':'#94a3b8'}}>Scoring against 254,000+ encoder variants…</div>
      </div>
    </div>
  );
}

function EmptyState({ dark=false }) {
  return (
    <div style={{display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',padding:'80px 0',gap:12}}>
      <svg width={48} height={48} viewBox="0 0 48 48" fill="none">
        <circle cx="24" cy="24" r="20" stroke={dark?'#334155':'#e2e8f0'} strokeWidth="2"/>
        <circle cx="24" cy="24" r="8" stroke={dark?'#334155':'#e2e8f0'} strokeWidth="2"/>
        <circle cx="24" cy="24" r="2" fill={dark?'#475569':'#cbd5e1'}/>
        <line x1="24" y1="4" x2="24" y2="16" stroke={dark?'#475569':'#cbd5e1'} strokeWidth="1.5"/>
        <line x1="24" y1="32" x2="24" y2="44" stroke={dark?'#475569':'#cbd5e1'} strokeWidth="1.5"/>
        <line x1="4" y1="24" x2="16" y2="24" stroke={dark?'#475569':'#cbd5e1'} strokeWidth="1.5"/>
        <line x1="32" y1="24" x2="44" y2="24" stroke={dark?'#475569':'#cbd5e1'} strokeWidth="1.5"/>
      </svg>
      <div style={{textAlign:'center'}}>
        <div style={{fontSize:15,fontWeight:600,color:dark?'#94a3b8':'#64748b',marginBottom:4}}>Enter a part number to begin</div>
        <div style={{fontSize:12.5,color:dark?'#475569':'#94a3b8'}}>Cross-reference against 254,000+ encoder variants</div>
      </div>
    </div>
  );
}

// ── AppNav ─────────────────────────────────────────────────────────────────
function AppNav({ page, setPage, user, dark, onLogout }) {
  const bg='#0f172a', border='#1e293b', active='#1855d4', activeBg='rgba(24,85,212,0.15)';
  const textMut='#64748b', textNorm='#94a3b8', textAct='#f1f5f9';
  const isAdmin=user.role==='superadmin';

  const navItem=(id,label,icon)=>{
    const isActive=page===id;
    return (
      <button key={id} onClick={()=>setPage(id)} style={{display:'flex',alignItems:'center',gap:10,padding:'9px 14px',borderRadius:6,width:'100%',background:isActive?activeBg:'transparent',border:'none',cursor:'pointer',color:isActive?textAct:textNorm,fontFamily:'IBM Plex Sans, sans-serif',fontSize:13,fontWeight:isActive?600:400,textAlign:'left'}}
        onMouseEnter={e=>{if(!isActive)e.currentTarget.style.background='rgba(255,255,255,0.04)';}}
        onMouseLeave={e=>{if(!isActive)e.currentTarget.style.background='transparent';}}>
        <span style={{color:isActive?textAct:textMut,flexShrink:0}}>{icon}</span>
        {label}
        {isActive&&<div style={{marginLeft:'auto',width:3,height:14,borderRadius:2,background:active}}/>}
      </button>
    );
  };

  return (
    <div style={{width:260,flexShrink:0,background:bg,borderRight:`1px solid ${border}`,display:'flex',flexDirection:'column',height:'100vh',position:'sticky',top:0}}>
      <div style={{padding:'20px 16px 14px',borderBottom:`1px solid ${border}`}}>
        <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}>
          <svg width={26} height={26} viewBox="0 0 26 26" fill="none">
            <circle cx="13" cy="13" r="12" fill="#1855d4" fillOpacity="0.15" stroke="#1855d4" strokeWidth="1.5"/>
            <circle cx="13" cy="13" r="6" stroke="#1855d4" strokeWidth="1.5"/>
            <circle cx="13" cy="13" r="2" fill="#1855d4"/>
            <line x1="13" y1="1" x2="13" y2="7" stroke="#1855d4" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="13" y1="19" x2="13" y2="25" stroke="#1855d4" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="1" y1="13" x2="7" y2="13" stroke="#1855d4" strokeWidth="1.5" strokeLinecap="round"/>
            <line x1="19" y1="13" x2="25" y2="13" stroke="#1855d4" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <span style={{fontSize:14,fontWeight:700,color:'#f1f5f9',letterSpacing:'-0.01em'}}>EncoderMatch</span>
        </div>
        <div style={{fontSize:10.5,color:'#475569',paddingLeft:34}}>
          <span style={{background:'#1e3a5f',color:'#60a5fa',padding:'1px 5px',borderRadius:3,fontSize:10,fontWeight:600}}>{user.client}</span>
        </div>
      </div>
      <div style={{padding:'10px 8px',flex:1}}>
        <div style={{marginBottom:4}}>
          {navItem('search','Cross-Reference',<svg width={15} height={15} viewBox="0 0 15 15" fill="none"><circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.4"/><line x1="9.5" y1="9.5" x2="13.5" y2="13.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>)}
          {navItem('history','Search History',<svg width={15} height={15} viewBox="0 0 15 15" fill="none"><circle cx="7.5" cy="7.5" r="6" stroke="currentColor" strokeWidth="1.4"/><path d="M7.5 4.5v3.5l2 2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>)}
          {navItem('weights','Scoring Weights',<svg width={15} height={15} viewBox="0 0 15 15" fill="none"><path d="M2 11h2.5M5 11V4M7.5 11h2.5M8 11V7M13 11h-2.5M10.5 11V9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>)}
        </div>
        {isAdmin&&(
          <div style={{marginTop:16}}>
            <div style={{fontSize:10,fontWeight:600,textTransform:'uppercase',letterSpacing:'0.08em',color:'#334155',padding:'0 6px 6px'}}>Admin</div>
            {navItem('admin','Console',<svg width={15} height={15} viewBox="0 0 15 15" fill="none"><rect x="1.5" y="2.5" width="12" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.4"/><line x1="5" y1="12" x2="10" y2="12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/><line x1="7.5" y1="11.5" x2="7.5" y2="13" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>)}
          </div>
        )}
      </div>
      <div style={{padding:'10px 12px 16px',borderTop:`1px solid ${border}`}}>
        <div style={{display:'flex',alignItems:'center',gap:9,marginBottom:10}}>
          <div style={{width:28,height:28,borderRadius:'50%',background:'#1e3a5f',border:'1px solid #1e40af',display:'flex',alignItems:'center',justifyContent:'center',fontSize:11,fontWeight:700,color:'#60a5fa',flexShrink:0}}>
            {user.name.split(' ').map(p=>p[0]).join('')}
          </div>
          <div style={{minWidth:0}}>
            <div style={{fontSize:12,fontWeight:600,color:'#e2e8f0',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{user.name}</div>
            <div style={{fontSize:10.5,color:'#475569',overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{user.email}</div>
          </div>
        </div>
        <button onClick={()=>onLogout()} style={{width:'100%',padding:'6px 0',background:'transparent',border:`1px solid ${border}`,borderRadius:5,cursor:'pointer',fontSize:11.5,color:'#475569',fontFamily:'IBM Plex Sans, sans-serif',display:'flex',alignItems:'center',justifyContent:'center',gap:6}}
          onMouseEnter={e=>e.currentTarget.style.borderColor='#334155'}
          onMouseLeave={e=>e.currentTarget.style.borderColor=border}>
          <svg width={11} height={11} viewBox="0 0 11 11" fill="none"><path d="M4 2H2a1 1 0 00-1 1v5a1 1 0 001 1h2M7 8l3-2.5L7 3M10 5.5H4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>
          Sign out
        </button>
      </div>
    </div>
  );
}

// ── LoginPage ──────────────────────────────────────────────────────────────
function LoginPage({ onLogin, dark }) {
  const [email,setEmail]=React.useState('');
  const [password,setPassword]=React.useState('');
  const [loading,setLoading]=React.useState(false);
  const [error,setError]=React.useState('');
  const [showPw,setShowPw]=React.useState(false);
  const aqbNavy='#1a3570', aqbOrange='#e87820';
  const border=dark?'#1e293b':'#e2e8f0', textPri=dark?'#f1f5f9':'#111827', textSec=dark?'#94a3b8':'#64748b', inputBg=dark?'#0f172a':'#f8fafc';
  const handleSubmit=async(e)=>{
    e.preventDefault();
    if(!email){setError('Email is required');return;}
    setError(''); setLoading(true);
    if (API_MODE==='live') {
      try {
        const resp=await fetch(`${FASTAPI_BASE_URL}/api/auth/login`,{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({email,password})
        });
        const data=await resp.json();
        if(!resp.ok){setError(data.detail||'Login failed');setLoading(false);return;}
        setLoading(false);
        onLogin(data.user.role, data.access_token, data.user);
      } catch(e) {
        setError('Could not reach server. Check connection.');
        setLoading(false);
      }
    } else {
      const isAdmin=email.includes('admin');
      setTimeout(()=>{setLoading(false);onLogin(isAdmin?'clientadmin':'enduser',null,null);},900);
    }
  };
  const iStyle={width:'100%',padding:'10px 12px',background:inputBg,border:`1px solid ${border}`,borderRadius:6,color:textPri,fontFamily:'IBM Plex Sans, sans-serif',fontSize:13.5,outline:'none',boxSizing:'border-box'};
  const lStyle={display:'block',fontSize:11.5,fontWeight:600,color:'#374151',marginBottom:6};
  return (
    <div style={{display:'flex',height:'100vh',fontFamily:'IBM Plex Sans, sans-serif',overflow:'hidden'}}>
      <div style={{width:'46%',flexShrink:0,background:aqbNavy,display:'flex',flexDirection:'column',padding:'48px 52px',position:'relative',overflow:'hidden'}}>
        <svg viewBox="0 0 500 500" style={{position:'absolute',right:-80,top:'50%',transform:'translateY(-50%)',width:520,height:520,opacity:0.07,pointerEvents:'none'}}>
          {[240,210,180,150,120,90,60,30].map(r=><circle key={r} cx="250" cy="250" r={r} fill="none" stroke="white" strokeWidth="1.2"/>)}
          {Array.from({length:72},(_,i)=>{const a=(i*5)*Math.PI/180,o=240,n=i%4===0?222:232;return<line key={i} x1={250+o*Math.cos(a)} y1={250+o*Math.sin(a)} x2={250+n*Math.cos(a)} y2={250+n*Math.sin(a)} stroke="white" strokeWidth={i%4===0?2:1}/>;}).filter(Boolean)}
          {[0,45,90,135,180,225,270,315].map(deg=>{const r=deg*Math.PI/180;return<line key={deg} x1={250+30*Math.cos(r)} y1={250+30*Math.sin(r)} x2={250+115*Math.cos(r)} y2={250+115*Math.sin(r)} stroke="white" strokeWidth="1"/>;}).filter(Boolean)}
          <circle cx="250" cy="250" r="18" fill="none" stroke="white" strokeWidth="2"/>
          <circle cx="250" cy="250" r="6" fill="white" opacity="0.5"/>
        </svg>
        <div style={{position:'relative',zIndex:1}}>
          <div style={{display:'inline-flex',alignItems:'center',background:'#ffffff',borderRadius:8,padding:'8px 14px',marginBottom:8}}>
            <span style={{fontSize:15,fontWeight:800,color:aqbNavy,letterSpacing:'0.02em',fontFamily:'IBM Plex Mono, monospace'}}>aqb</span>
            <span style={{fontSize:10,fontWeight:600,color:aqbOrange,marginLeft:4,letterSpacing:'0.04em'}}>SOLUTIONS</span>
          </div>
        </div>
        <div style={{flex:1,display:'flex',flexDirection:'column',justifyContent:'center',position:'relative',zIndex:1}}>
          <div style={{display:'inline-flex',alignItems:'center',gap:8,marginBottom:20}}>
            <div style={{width:36,height:36,borderRadius:9,background:aqbOrange,display:'flex',alignItems:'center',justifyContent:'center'}}>
              <svg width={20} height={20} viewBox="0 0 20 20" fill="none">
                <circle cx="10" cy="10" r="8.5" stroke="white" strokeWidth="1.5"/><circle cx="10" cy="10" r="4" stroke="white" strokeWidth="1.5"/><circle cx="10" cy="10" r="1.5" fill="white"/>
                <line x1="10" y1="1.5" x2="10" y2="6" stroke="white" strokeWidth="1.5" strokeLinecap="round"/>
                <line x1="10" y1="14" x2="10" y2="18.5" stroke="white" strokeWidth="1.5" strokeLinecap="round"/>
                <line x1="1.5" y1="10" x2="6" y2="10" stroke="white" strokeWidth="1.5" strokeLinecap="round"/>
                <line x1="14" y1="10" x2="18.5" y2="10" stroke="white" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            </div>
            <span style={{fontSize:13,fontWeight:600,color:'rgba(255,255,255,0.6)',letterSpacing:'0.04em',textTransform:'uppercase'}}>EncoderMatch</span>
          </div>
          <h1 style={{margin:'0 0 16px',fontSize:34,fontWeight:700,color:'#ffffff',letterSpacing:'-0.03em',lineHeight:1.2}}>AI-powered encoder<br/>cross-reference</h1>
          <p style={{margin:'0 0 40px',fontSize:14.5,color:'rgba(255,255,255,0.55)',lineHeight:1.65,maxWidth:320}}>Find compatible replacement encoders from 254,000+ variants across Kübler, EPC, and Sick catalogues — ranked by field-by-field compatibility score.</p>
          <div style={{display:'flex',flexDirection:'column',gap:10}}>
            {[{icon:'⚡',text:'Results in 2–5 seconds'},{icon:'🎯',text:'T2/T3 tiered scoring — physical + secondary specs'},{icon:'🔒',text:'Licence-controlled database access per user'}].map(f=>(
              <div key={f.text} style={{display:'flex',alignItems:'center',gap:10}}>
                <div style={{width:28,height:28,borderRadius:7,flexShrink:0,background:'rgba(255,255,255,0.08)',border:'1px solid rgba(255,255,255,0.12)',display:'flex',alignItems:'center',justifyContent:'center',fontSize:13}}>{f.icon}</div>
                <span style={{fontSize:13,color:'rgba(255,255,255,0.65)'}}>{f.text}</span>
              </div>
            ))}
          </div>
        </div>
        <div style={{position:'relative',zIndex:1}}>
          <div style={{height:1,background:'rgba(255,255,255,0.1)',marginBottom:16}}/>
          <p style={{fontSize:12,color:'rgba(255,255,255,0.3)',letterSpacing:'0.04em'}}>Technology Beyond Dimensions</p>
        </div>
      </div>
      <div style={{flex:1,background:dark?'#0a0f1a':'#f4f6fa',display:'flex',alignItems:'center',justifyContent:'center',padding:'40px',position:'relative'}}>
        <div style={{position:'absolute',inset:0,pointerEvents:'none',opacity:0.5,backgroundImage:`linear-gradient(#e2e8f0 1px,transparent 1px),linear-gradient(90deg,#e2e8f0 1px,transparent 1px)`,backgroundSize:'32px 32px'}}/>
        <div style={{width:'100%',maxWidth:400,position:'relative',zIndex:1}}>
          <h2 style={{margin:'0 0 4px',fontSize:22,fontWeight:700,color:textPri,letterSpacing:'-0.02em'}}>Sign in</h2>
          <p style={{margin:'0 0 28px',fontSize:13.5,color:textSec}}>Invite-only access — provisioned by your administrator.</p>

          {error&&<div style={{background:'#fef2f2',border:'1px solid #fecaca',borderRadius:6,padding:'9px 12px',marginBottom:16,fontSize:13,color:'#b91c1c'}}>{error}</div>}
          <div style={{background:dark?'#111827':'#fff',border:`1px solid ${border}`,borderRadius:10,padding:'24px',boxShadow:dark?'none':'0 2px 12px rgba(0,0,0,0.06)'}}>
            <form onSubmit={handleSubmit}>
              <div style={{marginBottom:16}}>
                <label style={lStyle}>Work email</label>
                <input type="email" value={email} onChange={e=>setEmail(e.target.value)} placeholder="you@company.com" style={iStyle} onFocus={e=>e.target.style.borderColor=aqbNavy} onBlur={e=>e.target.style.borderColor=border}/>
              </div>
              <div style={{marginBottom:22}}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:6}}>
                  <label style={{...lStyle,marginBottom:0}}>Password</label>
                  <button type="button" style={{background:'none',border:'none',cursor:'pointer',fontSize:12,color:aqbNavy,fontFamily:'IBM Plex Sans, sans-serif',padding:0}}>Forgot password?</button>
                </div>
                <div style={{position:'relative'}}>
                  <input type={showPw?'text':'password'} value={password} onChange={e=>setPassword(e.target.value)} placeholder="••••••••" style={{...iStyle,paddingRight:38}} onFocus={e=>e.target.style.borderColor=aqbNavy} onBlur={e=>e.target.style.borderColor=border}/>
                  <button type="button" onClick={()=>setShowPw(!showPw)} style={{position:'absolute',right:10,top:'50%',transform:'translateY(-50%)',background:'none',border:'none',cursor:'pointer',color:textSec,padding:0,display:'flex'}}>
                    <svg width={16} height={16} viewBox="0 0 16 16" fill="none"><path d="M2 8s2-4 6-4 6 4 6 4-2 4-6 4-6-4-6-4z" stroke="currentColor" strokeWidth="1.3"/><circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.3"/>{!showPw&&<line x1="2" y1="2" x2="14" y2="14" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>}</svg>
                  </button>
                </div>
              </div>
              <button type="submit" disabled={loading} style={{width:'100%',padding:'11px',background:loading?'#bfdbfe':aqbNavy,color:loading?'#1e40af':'white',border:'none',borderRadius:7,cursor:loading?'default':'pointer',fontFamily:'IBM Plex Sans, sans-serif',fontSize:14,fontWeight:600,display:'flex',alignItems:'center',justifyContent:'center',gap:8}}>
                {loading&&<div style={{width:14,height:14,border:'2px solid rgba(255,255,255,0.3)',borderTopColor:'white',borderRadius:'50%',animation:'spin 0.7s linear infinite'}}/>}
                {loading?'Signing in…':'Sign in'}
              </button>
            </form>
          </div>
          <p style={{textAlign:'center',marginTop:20,fontSize:12,color:'#94a3b8'}}>© 2026 AQB Solutions Private Ltd. · EncoderMatch v1.0</p>
        </div>
      </div>
    </div>
  );
}

// ── AI Explanation Tab (real Claude API) ───────────────────────────────────
function AIExplanationTab({ result, source, dark, blocks, status, setBlocks, setStatus }) {
  // State is lifted to ResultCard — no local state here.
  // This prevents re-fetching when the user switches tabs back to AI Explanation.
  const textPri=dark?'#f1f5f9':'#111827', textSec=dark?'#94a3b8':'#64748b';
  const levelStyle={
    good:    {bg:dark?'#0d2d1a':'#f0fdf4',border:dark?'#166534':'#bbf7d0',dot:'#16a34a',label:'MATCH'},
    warning: {bg:dark?'#2a1a00':'#fffbeb',border:dark?'#92400e':'#fde68a',dot:'#d97706',label:'NOTE'},
    issue:   {bg:dark?'#2a0a0a':'#fef2f2',border:dark?'#7f1d1d':'#fecaca',dot:'#dc2626',label:'RISK'},
    info:    {bg:dark?'#0a1628':'#f0f4ff',border:dark?'#1e3a5f':'#c7d7f9',dot:'#1a3570',label:'INFO'},
  };

  const generate=async()=>{
    setStatus('loading');
    try {
      const resp=await fetch(`${FASTAPI_BASE_URL}/api/explain`,{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({result,source})
      });
      if(!resp.ok) throw new Error(`API ${resp.status}`);
      const data=await resp.json();
      setBlocks(Array.isArray(data.blocks)?data.blocks:[]);
      setStatus('done');
    } catch(e) {
      setBlocks([{level:'warning',field:'overview',text:'Could not load AI analysis. Please retry.'}]);
      setStatus('error');
    }
  };

  // Only fetch once — status 'idle' means not yet fetched for this result card
  React.useEffect(()=>{ if(status==='idle') generate(); },[]);

  if (status==='loading') return (
    <div style={{padding:'36px 20px',display:'flex',flexDirection:'column',alignItems:'center',gap:12}}>
      <div style={{width:28,height:28,border:`3px solid ${dark?'#334155':'#e2e8f0'}`,borderTopColor:'#1a3570',borderRadius:'50%',animation:'spin 0.8s linear infinite'}}/>
      <div style={{fontSize:13,color:textSec}}>Generating AI analysis…</div>
      <div style={{fontSize:11.5,color:dark?'#475569':'#94a3b8'}}>Comparing {Object.keys(result.t2).length+Object.keys(result.t3).length} parameters</div>
    </div>
  );

  return (
    <div style={{padding:'14px 16px 16px',display:'flex',flexDirection:'column',gap:7}}>
      {status==='error'&&<button onClick={generate} style={{alignSelf:'flex-start',fontSize:12,color:'#1a3570',background:'none',border:'none',cursor:'pointer',textDecoration:'underline',fontFamily:'IBM Plex Sans, sans-serif',marginBottom:4}}>↺ Retry</button>}
      {blocks.map((b,i)=>{
        const s=levelStyle[b.level]||levelStyle.info, isOv=b.field==='overview';
        return (
          <div key={i} style={{background:s.bg,border:`1px solid ${s.border}`,borderRadius:7,padding:isOv?'12px 14px':'9px 14px',display:'flex',gap:10,alignItems:'flex-start'}}>
            <div style={{flexShrink:0,marginTop:isOv?4:3}}>
              {isOv
                ?<svg width={14} height={14} viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="6" fill={s.dot} fillOpacity="0.15" stroke={s.dot} strokeWidth="1.3"/><path d="M7 5v4M7 4v.5" stroke={s.dot} strokeWidth="1.5" strokeLinecap="round"/></svg>
                :<div style={{width:7,height:7,borderRadius:'50%',background:s.dot}}/>
              }
            </div>
            <div style={{flex:1}}>
              {!isOv&&<div style={{display:'flex',alignItems:'center',gap:6,marginBottom:3}}>
                <span style={{fontSize:10,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.08em',color:s.dot}}>{s.label}</span>
                <span style={{fontSize:11.5,fontWeight:600,color:textPri}}>{b.field}</span>
              </div>}
              <div style={{fontSize:isOv?13.5:13,color:textPri,lineHeight:1.55,fontWeight:isOv?500:400}}>{b.text}</div>
            </div>
          </div>
        );
      })}
      <div style={{fontSize:11,color:dark?'#334155':'#94a3b8',textAlign:'center',paddingTop:4,fontStyle:'italic'}}>AI-generated · Always verify against manufacturer datasheet</div>
    </div>
  );
}

// ── ResultCard ─────────────────────────────────────────────────────────────
function ResultCard({ result, source, expanded, onToggle, dark=false, animDelay=0 }) {
  const [visible,setVisible]=React.useState(false);
  const [activeTab,setActiveTab]=React.useState('breakdown');
  const [hovered,setHovered]=React.useState(false);
  // AI state lifted here so it persists across tab switches (no re-fetch on tab switch)
  const [aiBlocks,setAiBlocks]=React.useState([]);
  const [aiStatus,setAiStatus]=React.useState('idle');
  React.useEffect(()=>{const t=setTimeout(()=>setVisible(true),animDelay);return()=>clearTimeout(t);},[]);
  React.useEffect(()=>{if(!expanded)setActiveTab('breakdown');},[expanded]);
  const cardBg=dark?'#111827':'#ffffff', border=dark?'#1e293b':'#e2e8f0', borderH=dark?'#334155':'#cbd5e1';
  const textPri=dark?'#f1f5f9':'#111827', textSec=dark?'#94a3b8':'#64748b', textMut=dark?'#475569':'#94a3b8';
  const tabBg=dark?'#0f172a':'#f8fafc', tabActBg=dark?'#1e293b':'#ffffff';
  const t2Fields=Object.entries(result.t2), t3Fields=Object.entries(result.t3);
  const sortedT2=[...t2Fields].sort((a,b)=>(a[1].score??1)-(b[1].score??1));
  const sortedT3=[...t3Fields].sort((a,b)=>(a[1].score??1)-(b[1].score??1));
  const tabBtn=(id,label,icon)=>(
    <button onClick={()=>setActiveTab(id)} style={{padding:'8px 14px',border:'none',cursor:'pointer',fontFamily:'IBM Plex Sans, sans-serif',fontSize:12.5,fontWeight:activeTab===id?600:400,color:activeTab===id?(dark?'#f1f5f9':'#111827'):(dark?'#64748b':'#94a3b8'),background:activeTab===id?tabActBg:'transparent',borderRadius:'5px 5px 0 0',borderBottom:activeTab===id?'2px solid #1a3570':'2px solid transparent',display:'flex',alignItems:'center',gap:5}}>
      {icon}{label}
    </button>
  );
  return (
    <div onMouseEnter={()=>setHovered(true)} onMouseLeave={()=>setHovered(false)}
      style={{background:cardBg,border:`1px solid ${hovered?borderH:border}`,borderRadius:10,overflow:'hidden',flexShrink:0,transition:'opacity 0.4s ease,transform 0.4s ease,border-color 0.15s',opacity:visible?1:0,transform:visible?'translateY(0)':'translateY(12px)',boxShadow:dark?'none':(hovered?'0 4px 20px rgba(0,0,0,0.08)':'0 1px 4px rgba(0,0,0,0.04)')}}>
      <div style={{display:'flex',gap:0,padding:'16px 20px 14px'}}>
        <div style={{display:'flex',flexDirection:'column',alignItems:'center',gap:6,marginRight:18,flexShrink:0}}>
          <div style={{width:26,height:26,borderRadius:'50%',background:result.rank===1?'#1a3570':(dark?'#1e293b':'#f1f5f9'),border:`1.5px solid ${result.rank===1?'#1a3570':(dark?'#334155':'#e2e8f0')}`,display:'flex',alignItems:'center',justifyContent:'center',fontSize:11,fontWeight:700,color:result.rank===1?'#ffffff':textSec}}>
            {result.rank}
          </div>
          <ScoreGauge score={result.total_score} size={80} dark={dark}/>
        </div>
        <div style={{flex:1,minWidth:0}}>
          <div style={{display:'flex',alignItems:'flex-start',justifyContent:'space-between',gap:12,marginBottom:4}}>
            <div>
              <div style={{marginBottom:3}}><PartNum value={result.part_number} size={15} dark={dark}/></div>
              <div style={{fontSize:12.5,color:textSec}}>
                <span style={{fontWeight:600,color:dark?'#60a5fa':'#1a3570'}}>{result.manufacturer_full}</span>
                <span style={{margin:'0 6px',color:textMut}}>·</span>
                <span>Model {result.family}</span>
                {result.url_type==='family'&&<span style={{marginLeft:8,fontSize:10.5,fontWeight:500,color:textMut,background:dark?'#1e293b':'#f1f5f9',padding:'1px 5px',borderRadius:3,border:`1px solid ${border}`}}>family page</span>}
              </div>
            </div>
            <a href={result.product_url} target="_blank" rel="noopener noreferrer"
              style={{display:'flex',alignItems:'center',gap:5,padding:'6px 12px',borderRadius:6,background:dark?'#1e3a5f':'#eff6ff',border:`1px solid ${dark?'#1e40af':'#bfdbfe'}`,color:dark?'#60a5fa':'#1a3570',fontFamily:'IBM Plex Sans, sans-serif',fontSize:12,fontWeight:600,textDecoration:'none',flexShrink:0}}
              onMouseEnter={e=>e.currentTarget.style.background=dark?'#1e40af':'#dbeafe'}
              onMouseLeave={e=>e.currentTarget.style.background=dark?'#1e3a5f':'#eff6ff'}>
              View product
              <svg width={11} height={11} viewBox="0 0 11 11" fill="none"><path d="M2 9L9 2M9 2H4M9 2v5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </a>
          </div>
          <div style={{display:'flex',flexDirection:'column',gap:5,marginTop:12,marginBottom:10}}>
            <SubScoreBar label="Physical Match (T2)" score={result.t2_score} dark={dark}/>
            <SubScoreBar label="Secondary Specs (T3)" score={result.t3_score} dark={dark}/>
          </div>
          <CPRPanel result={result} sourceCpr={source.cpr_values} dark={dark}/>
        </div>
      </div>
      <button onClick={onToggle} style={{width:'100%',padding:'8px 20px',background:tabBg,borderTop:`1px solid ${border}`,border:'none',borderBottom:expanded?`1px solid ${border}`:'none',cursor:'pointer',textAlign:'left',display:'flex',alignItems:'center',gap:6,fontFamily:'IBM Plex Sans, sans-serif',fontSize:12,color:textMut}}
        onMouseEnter={e=>e.currentTarget.style.background=dark?'#1e293b':'#f1f5f9'}
        onMouseLeave={e=>e.currentTarget.style.background=tabBg}>
        <svg width={12} height={12} viewBox="0 0 12 12" fill="none" style={{transform:expanded?'rotate(180deg)':'rotate(0)',transition:'transform 0.2s'}}><path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>
        {expanded?'Hide':'Show'} details
        <span style={{fontSize:11,color:dark?'#334155':'#94a3b8',marginLeft:2}}>({t2Fields.length+t3Fields.length} parameters · AI explanation available)</span>
      </button>
      {expanded&&(
        <div>
          <div style={{display:'flex',gap:2,padding:'6px 12px 0',background:tabBg,borderBottom:`1px solid ${border}`}}>
            {tabBtn('breakdown','Field Breakdown',<svg width={12} height={12} viewBox="0 0 12 12" fill="none"><rect x="1" y="2" width="10" height="1.5" rx="0.75" fill="currentColor"/><rect x="1" y="5.25" width="10" height="1.5" rx="0.75" fill="currentColor"/><rect x="1" y="8.5" width="6" height="1.5" rx="0.75" fill="currentColor"/></svg>)}
            {tabBtn('ai','AI Explanation',<svg width={12} height={12} viewBox="0 0 12 12" fill="none"><path d="M6 1.5C3.5 1.5 1.5 3.3 1.5 5.5c0 .9.3 1.7.8 2.3L2 10.5l2.8-.8c.4.1.8.2 1.2.2 2.5 0 4.5-1.8 4.5-4S8.5 1.5 6 1.5z" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinejoin="round"/><circle cx="4.2" cy="5.5" r=".7" fill="currentColor"/><circle cx="6" cy="5.5" r=".7" fill="currentColor"/><circle cx="7.8" cy="5.5" r=".7" fill="currentColor"/></svg>)}
          </div>
          {activeTab==='breakdown'&&(
            <div style={{paddingBottom:8}}>
              {/* Manufacturer column headers */}
              {(()=>{
                const srcMfr=source.manufacturer||'Source';
                const candMfr=result.manufacturer_full||result.manufacturer||'Candidate';
                const hdrCol=dark?'#475569':'#94a3b8';
                return (
                  <div style={{display:'grid',gridTemplateColumns:'12px 1fr 8px 1fr 52px',gap:6,
                    padding:'4px 12px 2px',marginBottom:2}}>
                    <div/>
                    <span style={{fontSize:10,fontWeight:700,textTransform:'uppercase',
                      letterSpacing:'0.08em',color:dark?'#60a5fa':'#1a3570'}}>{srcMfr}</span>
                    <div/>
                    <span style={{fontSize:10,fontWeight:700,textTransform:'uppercase',
                      letterSpacing:'0.08em',color:dark?'#60a5fa':'#1a3570'}}>{candMfr}</span>
                    <div/>
                  </div>
                );
              })()}
              <TierDivider label="Physical Match · T2" score={result.t2_score} dark={dark}/>
              {sortedT2.map(([key,f])=><FieldRow key={key} label={f.label} srcVal={f.src_val} candVal={f.cand_val} score={f.score} srcLabel={f.src_native_label||''} candLabel={f.cand_native_label||''} dark={dark}/>)}
              <TierDivider label="Secondary Specs · T3" score={result.t3_score} dark={dark}/>
              {sortedT3.map(([key,f])=><FieldRow key={key} label={f.label} srcVal={f.src_val} candVal={f.cand_val} score={f.score} srcLabel={f.src_native_label||''} candLabel={f.cand_native_label||''} dark={dark}/>)}
              {result.extra&&Object.keys(result.extra).length>0&&(
                <>
                  <TierDivider label="Additional Specifications" score={null} dark={dark}/>
                  {Object.entries(result.extra).map(([key,f])=>(
                    <FieldRow key={key} label={f.label} srcVal={f.src_val} candVal={f.cand_val}
                      score={null} srcLabel={f.src_native_label||''} candLabel={f.cand_native_label||''}
                      dark={dark} unscored={true}/>
                  ))}
                </>
              )}
            </div>
          )}
          {activeTab==='ai'&&<AIExplanationTab result={result} source={source} dark={dark} blocks={aiBlocks} status={aiStatus} setBlocks={setAiBlocks} setStatus={setAiStatus}/>}
        </div>
      )}
    </div>
  );
}

// ── SourceCard ──────────────────────────────────────────────────────────────
function SourceCard({ source, resultCount, dark }) {
  const bg=dark?'#0a1628':'#eff6ff', border=dark?'#1e3a5f':'#bfdbfe';
  const textPri=dark?'#e2e8f0':'#1e3a8a', textSec=dark?'#60a5fa':'#1d4ed8';
  const mutedCol=dark?'#475569':'#6b83ba';
  const chipBg=dark?'#1e3a5f':'#dbeafe', chipBorder=dark?'#1e40af':'#93c3fd';

  // Parse CPR values (may be array or JSON string)
  let cprArr=[];
  try {
    const raw=source.cpr_values;
    if(Array.isArray(raw)) cprArr=raw;
    else if(typeof raw==='string') cprArr=JSON.parse(raw);
  } catch(_){}

  const specs=[
    ['Shaft type',    source.shaft_type==='solid'?'Solid shaft':(source.shaft_type||'—')],
    ['Housing dia.',  source.housing_diameter_mm?`ø${source.housing_diameter_mm} mm`:'—'],
    ['Shaft/bore dia.',source.shaft_bore_diameter_mm?`${source.shaft_bore_diameter_mm} mm`:'—'],
    ['IP rating',     source.ip_rating?`IP${source.ip_rating}`:'—'],
    ['Output circuit',source.output_circuit_canonical||'—'],
    ['Connection',    source.connection_type_canonical||'—'],
    ['Supply voltage',(source.supply_voltage_min_v!=null&&source.supply_voltage_max_v!=null)?`${source.supply_voltage_min_v}–${source.supply_voltage_max_v} V`:'—'],
    ['Max temp',      source.operating_temp_max_c!=null?`${source.operating_temp_max_c} °C`:'—'],
    ['Sensing',       source.sensing_method||'—'],
    ['Shock resist.', source.shock_resistance_ms2!=null?`${source.shock_resistance_ms2} m/s²`:'—'],
  ].filter(([,v])=>v&&v!=='—');

  return (
    <div style={{background:bg,border:`1px solid ${border}`,borderRadius:10,padding:'14px 20px',flexShrink:0,boxShadow:dark?'none':'0 1px 4px rgba(29,78,216,0.06)'}}>
      {/* Header */}
      <div style={{display:'flex',alignItems:'flex-start',justifyContent:'space-between',marginBottom:12}}>
        <div style={{display:'flex',gap:14,alignItems:'flex-start'}}>
          {/* Encoder icon */}
          <div style={{width:38,height:38,borderRadius:'50%',background:chipBg,border:`1.5px solid ${chipBorder}`,display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0,marginTop:2}}>
            <svg width={20} height={20} viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="5.5" stroke={textSec} strokeWidth="1.3"/>
              <circle cx="7" cy="7" r="2.5" stroke={textSec} strokeWidth="1.3"/>
              <circle cx="7" cy="7" r="1" fill={textSec}/>
              <line x1="7" y1="1.5" x2="7" y2="3.2" stroke={textSec} strokeWidth="1.3" strokeLinecap="round"/>
              <line x1="7" y1="10.8" x2="7" y2="12.5" stroke={textSec} strokeWidth="1.3" strokeLinecap="round"/>
              <line x1="1.5" y1="7" x2="3.2" y2="7" stroke={textSec} strokeWidth="1.3" strokeLinecap="round"/>
              <line x1="10.8" y1="7" x2="12.5" y2="7" stroke={textSec} strokeWidth="1.3" strokeLinecap="round"/>
            </svg>
          </div>
          <div>
            <div style={{display:'flex',alignItems:'center',gap:7,marginBottom:4}}>
              <span style={{fontSize:10,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.08em',background:chipBg,color:textSec,padding:'2px 7px',borderRadius:3,border:`1px solid ${chipBorder}`}}>Source</span>
              <span style={{fontWeight:600,color:dark?'#60a5fa':'#1d4ed8',fontSize:12.5}}>{source.manufacturer}</span>
              <span style={{color:mutedCol,opacity:0.5}}>·</span>
              <span style={{fontSize:12.5,color:mutedCol}}>Model {source.family}</span>
            </div>
            <div style={{fontFamily:'IBM Plex Mono, monospace',fontSize:15,fontWeight:700,color:textPri}}>{source.part_number}</div>
          </div>
        </div>
        {resultCount!=null&&(
          <div style={{fontSize:12.5,fontWeight:700,color:textPri,flexShrink:0,textAlign:'right'}}>
            {resultCount} <span style={{fontWeight:400,color:mutedCol}}>match{resultCount!==1?'es':''} found</span>
          </div>
        )}
      </div>

      {/* Divider */}
      <div style={{height:1,background:border,margin:'0 0 12px'}}/>

      {/* Specs grid */}
      {specs.length>0&&(
        <div style={{display:'grid',gridTemplateColumns:'repeat(5,1fr)',gap:'7px 14px',marginBottom:cprArr.length>0?12:0}}>
          {specs.map(([label,val])=>(
            <div key={label}>
              <div style={{fontSize:10,fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:mutedCol,marginBottom:2}}>{label}</div>
              <div style={{fontSize:12,fontWeight:600,color:textPri}}>{val}</div>
            </div>
          ))}
        </div>
      )}

      {/* CPR values */}
      {cprArr.length>0&&(
        <div style={{display:'flex',alignItems:'center',gap:5,flexWrap:'wrap',paddingTop:10,borderTop:`1px solid ${border}`}}>
          <span style={{fontSize:10,fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:mutedCol,flexShrink:0,marginRight:2}}>PPR values</span>
          {cprArr.map(v=>(
            <span key={v} style={{fontSize:11,padding:'2px 7px',borderRadius:3,fontFamily:'IBM Plex Mono, monospace',background:chipBg,color:textSec,border:`1px solid ${chipBorder}`}}>{v.toLocaleString()}</span>
          ))}
        </div>
      )}
    </div>
  );
}


// ── Weight configuration defaults (mirrors matcher_config.json) ─────────────
const DEFAULT_T2_WEIGHTS = {
  cpr_values: 3, ip_rating: 2, connection_type_canonical: 1.5,
  output_circuit_canonical: 1.5, housing_diameter_mm: 1, shaft_bore_diameter_mm: 1,
};
const DEFAULT_T3_WEIGHTS = {
  supply_voltage: 2.5, sensing_method: 2, operating_temp_max_c: 1.5,
  shock_resistance_ms2: 1.5, shaft_load_radial_n: 1,
  vibration_resistance_ms2: 1, connector_pins: 0.5,
};
const T2_LABELS = {
  cpr_values:'PPR Coverage', ip_rating:'IP Rating',
  connection_type_canonical:'Connection Type', output_circuit_canonical:'Output Circuit',
  housing_diameter_mm:'Housing Diameter', shaft_bore_diameter_mm:'Bore Diameter',
};
const T3_LABELS = {
  supply_voltage:'Supply Voltage', sensing_method:'Sensing Method',
  operating_temp_max_c:'Max Operating Temp', shock_resistance_ms2:'Shock Resistance',
  shaft_load_radial_n:'Shaft Load', vibration_resistance_ms2:'Vibration',
  connector_pins:'Connector Pins',
};
function normalizeWeights(raw) {
  const total = Object.values(raw).reduce((s,v)=>s+v, 0);
  if (total === 0) return raw;
  return Object.fromEntries(Object.entries(raw).map(([k,v])=>[k, parseFloat((v/total).toFixed(4))]));
}

// ── SearchPanel ─────────────────────────────────────────────────────────────
function SearchPanel({ onSearch, user, searchState, dark, t2Raw, t3Raw, authToken }) {
  const isAdmin=user.role==='superadmin';
  const [partNum,setPartNum]=React.useState('8.KIS40.1342.1024');
  const [source,setSource]=React.useState(()=>isAdmin?'kubler':(user.allowed_sources||['kubler'])[0]||'kubler');
  const [targets,setTargets]=React.useState({epc:true,sick:false,posital:false,kubler:false});
  const isEndUser=user.role==='enduser';
  const END_USER_MAX_RESULTS=3;
  const [topN,setTopN]=React.useState(isAdmin?10:isEndUser?END_USER_MAX_RESULTS:5);
  const [detectedMfr,setDetectedMfr]=React.useState(null);
  const [detecting,setDetecting]=React.useState(false);
  const detectRef=React.useRef(null);
  // Keep a ref so the async detect callback always sees current source value
  const sourceRef=React.useRef(source);
  React.useEffect(()=>{ sourceRef.current=source; },[source]);
  // Flags to prevent loops: skip first source render + skip detect-triggered source changes
  const isFirstSourceEffect=React.useRef(true);
  const skipNextSourceEffect=React.useRef(false);

  const runDetect=React.useCallback(async(val)=>{
    if(!val.trim()||!authToken) return;
    setDetecting(true);
    try {
      const resp=await fetch(`${FASTAPI_BASE_URL}/api/parts/detect?q=${encodeURIComponent(val.trim())}`,{
        headers:{'Authorization':`Bearer ${authToken}`}
      });
      if(resp.ok){
        const data=await resp.json();
        const availSrc=isAdmin?ALL_MANUFACTURERS:(user.allowed_sources||[]);
        if(data.manufacturer&&data.manufacturer!==sourceRef.current&&availSrc.includes(data.manufacturer)){
          skipNextSourceEffect.current=true;     // this setSource is from detect — don't re-detect
          sourceRef.current=data.manufacturer;   // immediate — prevents stale closure on rapid search click
          setSource(data.manufacturer);
          setTargets(t=>({...t,[data.manufacturer]:false}));  // remove detected mfr from targets to prevent self-match
          setDetectedMfr(data.manufacturer);
        }
      }
    } catch(_){}
    setDetecting(false);
  },[authToken,isAdmin,user.allowed_sources]);

  // Fire detect on mount for any pre-filled part number (e.g. default value)
  React.useEffect(()=>{
    if(!partNum.trim()||!authToken) return;
    const timer=setTimeout(()=>runDetect(partNum),400);
    return ()=>clearTimeout(timer);
  },[]);  // eslint-disable-line — intentionally run once on mount

  // Re-detect when user manually changes the source dropdown
  React.useEffect(()=>{
    if(isFirstSourceEffect.current){isFirstSourceEffect.current=false;return;}
    if(skipNextSourceEffect.current){skipNextSourceEffect.current=false;return;}
    if(!partNum.trim()||!authToken) return;
    if(detectRef.current) clearTimeout(detectRef.current);
    detectRef.current=setTimeout(()=>runDetect(partNum),600);
  },[source]);  // eslint-disable-line — only source dep intentional

  const handlePartNumChange=(val)=>{
    setPartNum(val);
    setDetectedMfr(null);
    if(detectRef.current) clearTimeout(detectRef.current);
    if(!val.trim()||!authToken) return;
    detectRef.current=setTimeout(()=>runDetect(val),600);
  };
  const bg=dark?'#111827':'#ffffff', border=dark?'#1e293b':'#e2e8f0';
  const textPri=dark?'#f1f5f9':'#111827', textSec=dark?'#64748b':'#94a3b8', inputBg=dark?'#0f172a':'#f8fafc';
  const locked=!isAdmin&&user.searches_used>=user.searches_limit;
  const anyTarget=Object.values(targets).some(Boolean);
  const toggleTarget=(key)=>!locked&&setTargets(t=>({...t,[key]:!t[key]}));
  const swapSourceTarget=()=>{const ft=Object.entries(targets).find(([,v])=>v)?.[0];if(!ft)return;setSource(ft);setTargets({...Object.fromEntries(ALL_MANUFACTURERS.map(m=>[m,false])),[source]:true});};
  const availableSources=isAdmin?ALL_MANUFACTURERS:user.allowed_sources;
  const availableTargets=isAdmin?ALL_MANUFACTURERS.filter(m=>m!==source):user.allowed_targets;
  return (
    <div style={{width:268,flexShrink:0,background:bg,borderRight:`1px solid ${border}`,display:'flex',flexDirection:'column',padding:'20px 16px',gap:16,overflowY:'auto'}}>
      <div style={{fontSize:13,fontWeight:700,color:dark?'#94a3b8':'#374151',letterSpacing:'-0.01em'}}>{isAdmin?'Bidirectional Search':'Find Replacements'}</div>
      <div>
        <label style={{display:'block',fontSize:11,fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:textSec,marginBottom:5}}>Part Number</label>
        <input value={partNum} onChange={e=>handlePartNumChange(e.target.value)} placeholder="e.g. 8.KIS40.1342.1024" disabled={locked}
          style={{width:'100%',boxSizing:'border-box',padding:'9px 10px',fontFamily:'IBM Plex Mono, monospace',fontSize:13,background:locked?(dark?'#1e293b':'#f8fafc'):inputBg,border:`1px solid ${border}`,borderRadius:6,color:locked?textSec:textPri,outline:'none'}}
          onFocus={e=>{if(!locked)e.target.style.borderColor='#1a3570';}} onBlur={e=>e.target.style.borderColor=border}/>
        {detectedMfr&&<div style={{marginTop:5,fontSize:11,color:dark?'#34d399':'#059669',display:'flex',alignItems:'center',gap:4}}>
          <svg width={10} height={10} viewBox="0 0 10 10" fill="none"><circle cx="5" cy="5" r="4" stroke="currentColor" strokeWidth="1.2"/><path d="M3 5l1.5 1.5L7 3.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>
          Auto-detected: {MFR_LABELS[detectedMfr]||detectedMfr}
        </div>}
      </div>
      <div>
        <label style={{display:'block',fontSize:11,fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:textSec,marginBottom:5}}>Source Manufacturer</label>
        {isAdmin
          ?<select value={source} onChange={e=>{setSource(e.target.value);setTargets(t=>({...t,[e.target.value]:false}));}} style={{width:'100%',padding:'8px 10px',background:inputBg,border:`1px solid ${border}`,borderRadius:6,color:textPri,fontFamily:'IBM Plex Sans, sans-serif',fontSize:13,outline:'none',cursor:'pointer'}}>
              {availableSources.map(m=><option key={m} value={m}>{MFR_LABELS[m]}</option>)}
            </select>
          :<select value={source} onChange={e=>setSource(e.target.value)} style={{width:'100%',padding:'8px 10px',background:inputBg,border:`1px solid ${dark?'#1e3a5f':'#bfdbfe'}`,borderRadius:6,color:dark?'#93c5fd':'#1e40af',fontFamily:'IBM Plex Sans, sans-serif',fontSize:13,fontWeight:600,outline:'none',cursor:'pointer'}}>
              {availableSources.map(m=><option key={m} value={m}>{MFR_LABELS[m]}</option>)}
            </select>
        }
      </div>
      {isAdmin&&(
        <button onClick={swapSourceTarget} style={{display:'flex',alignItems:'center',justifyContent:'center',gap:6,padding:'6px',borderRadius:6,cursor:'pointer',width:'100%',background:'transparent',border:`1px dashed ${border}`,color:textSec,fontFamily:'IBM Plex Sans, sans-serif',fontSize:12}}
          onMouseEnter={e=>{e.currentTarget.style.borderColor='#1a3570';e.currentTarget.style.color=dark?'#93c5fd':'#1a3570';}}
          onMouseLeave={e=>{e.currentTarget.style.borderColor=border;e.currentTarget.style.color=textSec;}}>
          <svg width={14} height={14} viewBox="0 0 14 14" fill="none"><path d="M2 5h10M9 2l3 3-3 3M12 9H2M5 6l-3 3 3 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>
          Swap source ↔ target
        </button>
      )}
      <div>
        <label style={{display:'block',fontSize:11,fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:textSec,marginBottom:5}}>{isAdmin?'Search Against':'Target (Locked)'}</label>
        {isAdmin
          ? availableTargets.map(db=>(
              <label key={db} style={{display:'flex',alignItems:'center',gap:8,padding:'7px 8px',borderRadius:5,marginBottom:3,cursor:locked?'default':'pointer',background:targets[db]?(dark?'#0f1f3d':'#eff6ff'):'transparent',border:`1px solid ${targets[db]?(dark?'#1e40af':'#bfdbfe'):(dark?'#1e293b':'#f1f5f9')}`}}>
                <div style={{width:15,height:15,borderRadius:3,flexShrink:0,background:targets[db]?'#1a3570':(dark?'#1e293b':'#f8fafc'),border:`1.5px solid ${targets[db]?'#1a3570':(dark?'#334155':'#d1d5db')}`,display:'flex',alignItems:'center',justifyContent:'center'}}>
                  {targets[db]&&<svg width={9} height={9} viewBox="0 0 9 9" fill="none"><path d="M1.5 4.5l2 2L7.5 2" stroke="white" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                </div>
                <input type="checkbox" checked={!!targets[db]} onChange={()=>toggleTarget(db)} style={{display:'none'}}/>
                <span style={{fontSize:13,fontWeight:500,color:dark?'#e2e8f0':'#374151'}}>{MFR_LABELS[db]}</span>
              </label>
            ))
          : <div style={{padding:'9px 12px',background:dark?'#0f1f3d':'#eff6ff',border:`1px solid ${dark?'#1e40af':'#bfdbfe'}`,borderRadius:6,display:'flex',alignItems:'center',gap:8}}>
              <svg width={12} height={12} viewBox="0 0 12 12" fill="none"><rect x="1" y="4" width="8" height="7" rx="1" stroke={dark?'#60a5fa':'#1a3570'} strokeWidth="1.3"/><path d="M3 4V3a2 2 0 014 0v1" stroke={dark?'#60a5fa':'#1a3570'} strokeWidth="1.3" strokeLinecap="round"/></svg>
              <span style={{fontSize:13,fontWeight:600,color:dark?'#93c5fd':'#1a3570'}}>{MFR_LABELS[user.client]||user.client}</span>
              <span style={{marginLeft:'auto',fontSize:10,color:dark?'#475569':'#93c5fd',fontWeight:500}}>locked</span>
            </div>
        }
      </div>
      {/* Number of results — adjustable for admin, read-only for enduser */}
      {(isAdmin||isEndUser)&&<div>
        <label style={{display:'block',fontSize:11,fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:textSec,marginBottom:5}}>Results to show</label>
        <div style={{display:'flex',alignItems:'center',border:`1px solid ${border}`,borderRadius:6,overflow:'hidden',background:inputBg,opacity:isEndUser?0.6:1}}>
          <button onClick={()=>!isEndUser&&setTopN(n=>Math.max(1,n-1))} style={{width:34,height:34,background:'transparent',border:'none',cursor:isEndUser?'not-allowed':'pointer',fontSize:18,color:textSec,display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0,lineHeight:1}}
            onMouseEnter={e=>{if(!isEndUser)e.currentTarget.style.background=dark?'#1e293b':'#f1f5f9'}}
            onMouseLeave={e=>e.currentTarget.style.background='transparent'}>−</button>
          <span style={{flex:1,textAlign:'center',fontSize:13,fontWeight:700,color:textPri,fontVariantNumeric:'tabular-nums'}}>{topN}</span>
          <button onClick={()=>!isEndUser&&setTopN(n=>Math.min(50,n+1))} style={{width:34,height:34,background:'transparent',border:'none',cursor:isEndUser?'not-allowed':'pointer',fontSize:18,color:textSec,display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0,lineHeight:1}}
            onMouseEnter={e=>{if(!isEndUser)e.currentTarget.style.background=dark?'#1e293b':'#f1f5f9'}}
            onMouseLeave={e=>e.currentTarget.style.background='transparent'}>+</button>
        </div>
        {isEndUser&&<div style={{fontSize:10.5,color:textSec,marginTop:4}}>Restricted to {END_USER_MAX_RESULTS} results for your account</div>}
      </div>}


      {/* Search button */}
      <button onClick={()=>!locked&&anyTarget&&partNum.trim()&&!detecting&&onSearch(partNum,sourceRef.current,isAdmin?targets:{[user.client]:true},isEndUser?END_USER_MAX_RESULTS:topN,{tier2:normalizeWeights(t2Raw),tier3:normalizeWeights(t3Raw)})} disabled={locked||!anyTarget||!partNum.trim()||detecting}
        style={{width:'100%',padding:'10px',background:(locked||!anyTarget||!partNum.trim()||detecting)?(dark?'#1e293b':'#f1f5f9'):'#1a3570',color:(locked||!anyTarget||!partNum.trim()||detecting)?textSec:'white',border:'none',borderRadius:7,fontFamily:'IBM Plex Sans, sans-serif',fontSize:13.5,fontWeight:600,cursor:(locked||!anyTarget||!partNum.trim()||detecting)?'not-allowed':'pointer',display:'flex',alignItems:'center',justifyContent:'center',gap:7}}>
        {searchState==='loading'
          ?<><div style={{width:13,height:13,border:'2px solid rgba(255,255,255,0.4)',borderTopColor:'white',borderRadius:'50%',animation:'spin 0.7s linear infinite'}}/>Matching…</>
          :detecting
            ?<><div style={{width:13,height:13,border:'2px solid rgba(255,255,255,0.4)',borderTopColor:'white',borderRadius:'50%',animation:'spin 0.7s linear infinite'}}/>Detecting source…</>
            :<><svg width={14} height={14} viewBox="0 0 14 14" fill="none"><circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.5"/><line x1="9.5" y1="9.5" x2="13" y2="13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>Find Replacements</>
        }
      </button>
      <div style={{display:'flex',alignItems:'center',gap:7,fontSize:11.5,color:dark?'#475569':'#94a3b8',padding:'8px 10px',borderRadius:6,background:dark?'#0f172a':'#f8fafc',border:`1px solid ${dark?'#1e293b':'#f1f5f9'}`}}>
        {isAdmin
          ?<><svg width={14} height={14} viewBox="0 0 14 14" fill="none"><path d="M2 5h10M9 2l3 3-3 3M12 9H2M5 6l-3 3 3 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg><span style={{color:dark?'#a78bfa':'#7c3aed',fontWeight:600}}>Bidirectional</span> — AQB access</>
          :<><svg width={12} height={12} viewBox="0 0 12 12" fill="none"><path d="M2 6h8M6 3l4 3-4 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>Source-only matching</>
        }
      </div>
      {!isAdmin&&<SearchCounter used={user.searches_used} limit={user.searches_limit} dark={dark}/>}
      {locked&&(
        <div style={{background:dark?'#0f172a':'#fef2f2',border:`1px solid ${dark?'#7f1d1d':'#fecaca'}`,borderRadius:8,padding:'14px'}}>
          <div style={{display:'flex',alignItems:'center',gap:7,marginBottom:8}}>
            <svg width={16} height={16} viewBox="0 0 16 16" fill="none"><rect x="3" y="7" width="10" height="8" rx="1.5" fill={dark?'#ef4444':'#dc2626'}/><path d="M5 7V5a3 3 0 016 0v2" stroke={dark?'#ef4444':'#dc2626'} strokeWidth="1.5" fill="none" strokeLinecap="round"/></svg>
            <span style={{fontSize:12.5,fontWeight:700,color:dark?'#fca5a5':'#b91c1c'}}>Search limit reached</span>
          </div>
          <p style={{margin:'0 0 8px',fontSize:12,color:dark?'#94a3b8':'#64748b',lineHeight:1.5}}>You've used all {user.searches_limit} searches for this period. Contact your administrator.</p>
          <a href={`mailto:${user.admin_email}`} style={{display:'flex',alignItems:'center',gap:5,fontSize:12,fontWeight:600,color:'#1a3570',textDecoration:'none'}}>
            <svg width={12} height={12} viewBox="0 0 12 12" fill="none"><rect x="1" y="2.5" width="10" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.2"/><path d="M1 4l5 3.5L11 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>
            {user.admin_email}
          </a>
        </div>
      )}
    </div>
  );
}

// ── SearchPage ──────────────────────────────────────────────────────────────
function SearchPage({ user, dark, authToken, setUser, t2Raw, t3Raw,
  liveResults, setLiveResults, liveSource, setLiveSource,
  searchState, setSearchState, expandedCards, setExpandedCards,
  searchError, setSearchError, lastPartNum, setLastPartNum,
  lastTopN, setLastTopN, lastElapsed, setLastElapsed,
  connectionType, setConnectionType }) {

  const displayResults = (API_MODE==='live'&&liveResults) ? liveResults : MOCK_DATA.results;
  const displaySource  = (API_MODE==='live'&&liveSource)  ? liveSource  : MOCK_DATA.source;

  const handleSearch=async(partNum,source,targets,topN=10,customWeights=null)=>{
    setSearchState('loading');
    setExpandedCards({});
    setSearchError(null);
    setLastPartNum(partNum);
    setLastTopN(topN);

    if (API_MODE==='live') {
      try {
        const resp=await fetch(`${FASTAPI_BASE_URL}/api/match`,{
          method:'POST',
          headers:{'Content-Type':'application/json','Authorization':`Bearer ${authToken}`},
          body:JSON.stringify({
            part_number:partNum,
            source_mfr:source,
            target_mfrs:Object.entries(targets).filter(([,v])=>v).map(([k])=>k),
            top_n:topN,
            custom_weights:customWeights,
          })
        });
        const data=await resp.json();
        if (resp.status===403) {
          // Search limit reached — update user state and show locked
          if(setUser) setUser(u=>({...u,searches_used:u?.searches_limit||100}));
          setSearchState('idle');
          return;
        }
        if (resp.status===404) {
          setSearchError(data.detail||'Part not found in database.');
          setSearchState('idle');
          return;
        }
        if (!resp.ok) {
          setSearchError(data.detail||'Match failed. Please try again.');
          setSearchState('idle');
          return;
        }
        setLiveResults(data.results);
        setLiveSource(data.source);
        setLastElapsed(data.elapsed_s||null);
        setConnectionType(data.connection_type||null);
        // Update search counter in user state
        if(setUser) setUser(u=>({...u,searches_used:data.searches_used,searches_remaining:data.searches_remaining}));
        setSearchState('results');
      } catch(e) {
        console.error('API error:',e);
        setSearchError('Could not reach server. Check connection.');
        setSearchState('idle');
      }
    } else {
      setTimeout(()=>setSearchState('results'),2200);
    }
  };

  const toggleCard=(rank)=>setExpandedCards(s=>({...s,[rank]:!s[rank]}));
  const bg=dark?'#0a0f1a':'#f4f6fa', textSec=dark?'#64748b':'#94a3b8';
  const errorBg=dark?'#450a0a':'#fef2f2', errorBorder=dark?'#7f1d1d':'#fecaca';

  return (
    <div style={{display:'flex',flex:1,overflow:'hidden'}}>
      <SearchPanel onSearch={handleSearch} user={user} searchState={searchState} dark={dark} t2Raw={t2Raw} t3Raw={t3Raw} authToken={authToken}/>
      <div style={{flex:1,background:bg,overflowY:'auto',padding:'20px 24px',display:'flex',flexDirection:'column',gap:14}}>
        {searchError&&(
          <div style={{background:errorBg,border:`1px solid ${errorBorder}`,borderRadius:8,padding:'12px 16px',fontSize:13,color:dark?'#fca5a5':'#b91c1c',display:'flex',alignItems:'center',gap:8}}>
            <svg width={14} height={14} viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.3"/><path d="M7 4v3.5M7 9.5v.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
            {searchError}
          </div>
        )}
        {searchState!=='idle'&&<SourceCard source={displaySource} resultCount={searchState==='results'?displayResults.length:null} dark={dark}/>}
        {searchState==='idle'&&!searchError&&<EmptyState dark={dark}/>}
        {searchState==='loading'&&<LoadingSpinner part={lastPartNum||displaySource.part_number} dark={dark}/>}
        {searchState==='results'&&displayResults.map((r,i)=>(
        <ErrorBoundary key={r.rank}>
        <ResultCard result={r} source={displaySource} expanded={!!expandedCards[r.rank]} onToggle={()=>toggleCard(r.rank)} dark={dark} animDelay={i*150}/>
        </ErrorBoundary>
        ))}
        {searchState==='results'&&<div style={{fontSize:11.5,color:textSec,textAlign:'center',padding:'8px 0 16px',flexShrink:0}}>Ranked by match score (T2 physical ×70% + T3 secondary ×30%) · {displayResults.length} match{displayResults.length!==1?'es':''} found (up to {lastTopN} requested){lastElapsed?` · ${parseFloat(lastElapsed).toFixed(1)}s${connectionType?` (${connectionType})`:''}`:''}</div>}
      </div>
    </div>
  );
}

// ── HistoryPage ─────────────────────────────────────────────────────────────
function HistoryPage({ user, onRerun, dark, authToken }) {
  const [historyData,setHistoryData]=React.useState(null);
  const data=MOCK_DATA; // fallback for mock mode

  React.useEffect(()=>{
    if (API_MODE!=='live' || !authToken) return;
    fetch(`${FASTAPI_BASE_URL}/api/history`,{
      headers:{'Authorization':`Bearer ${authToken}`}
    })
    .then(r=>r.json())
    .then(d=>{
      // Normalise history records to match frontend table format
      const records=(d.history||[]).map((r,i)=>({
        id: i+1,
        ts: (r.timestamp||'').slice(0,16).replace('T',' '),
        src_part: r.src_part||'',
        targets: r.target_mfrs||[],
        top_match: r.top_match||'—',
        top_score: parseFloat(r.top_score||0),
        n: r.search_number||0,
      }));
      setHistoryData(records);
    })
    .catch(e=>console.error('History fetch error:',e));
  },[authToken]);

  const displayHistory = (API_MODE==='live'&&historyData) ? historyData : data.history;
  const bg=dark?'#0a0f1a':'#f4f6fa', cardBg=dark?'#111827':'#ffffff', border=dark?'#1e293b':'#e2e8f0';
  const textPri=dark?'#f1f5f9':'#111827', textSec=dark?'#94a3b8':'#64748b', textMut=dark?'#475569':'#94a3b8';
  const [hovered,setHovered]=React.useState(null);
  const pct=user.searches_used/user.searches_limit;
  return (
    <div style={{flex:1,background:bg,overflowY:'auto',padding:'24px 28px'}}>
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:20}}>
        <div>
          <h2 style={{margin:0,fontSize:18,fontWeight:700,color:textPri,letterSpacing:'-0.02em'}}>Search History</h2>
          <p style={{margin:'3px 0 0',fontSize:13,color:textSec}}>Your past {data.history.length} searches · {user.searches_used} of {user.searches_limit} used this period</p>
        </div>
        <div style={{background:cardBg,border:`1px solid ${border}`,borderRadius:8,padding:'10px 16px',display:'flex',alignItems:'center',gap:12}}>
          <div>
            <div style={{fontSize:11,fontWeight:600,color:textMut,textTransform:'uppercase',letterSpacing:'0.06em',marginBottom:4}}>Usage this period</div>
            <div style={{width:140,height:5,borderRadius:3,background:dark?'#334155':'#e2e8f0',overflow:'hidden'}}>
              <div style={{width:`${pct*100}%`,height:'100%',borderRadius:3,background:pct>=0.9?'#dc2626':pct>=0.8?'#d97706':'#1855d4'}}/>
            </div>
          </div>
          <span style={{fontSize:13,fontWeight:700,color:textPri,fontVariantNumeric:'tabular-nums'}}>{user.searches_used}<span style={{fontSize:11,fontWeight:400,color:textSec}}>/{user.searches_limit}</span></span>
        </div>
      </div>
      <div style={{background:cardBg,border:`1px solid ${border}`,borderRadius:10,overflow:'hidden',boxShadow:dark?'none':'0 1px 4px rgba(0,0,0,0.04)'}}>
        <div style={{display:'grid',gridTemplateColumns:'160px 1fr 120px 180px 90px 60px',gap:0,padding:'10px 20px',background:dark?'#0f172a':'#f8fafc',borderBottom:`1px solid ${border}`}}>
          {['Timestamp','Source Part','Targets','Top Match','Score','#'].map(h=><span key={h} style={{fontSize:11,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.06em',color:textMut}}>{h}</span>)}
        </div>
        {displayHistory.map((row,i)=>{
          const theme=scoreTheme(row.top_score), isHov=hovered===row.id;
          return (
            <div key={row.id} onClick={()=>onRerun&&onRerun(row)} onMouseEnter={()=>setHovered(row.id)} onMouseLeave={()=>setHovered(null)}
              style={{display:'grid',gridTemplateColumns:'160px 1fr 120px 180px 90px 60px',gap:0,padding:'11px 20px',borderBottom:i<data.history.length-1?`1px solid ${border}`:'none',background:isHov?(dark?'#1e293b':'#f8fafc'):'transparent',cursor:'pointer',alignItems:'center',transition:'background 0.12s'}}>
              <span style={{fontSize:12,color:textSec,fontVariantNumeric:'tabular-nums'}}>{row.ts}</span>
              <span style={{fontFamily:'IBM Plex Mono, monospace',fontSize:12.5,color:textPri,fontWeight:500}}>{row.src_part}</span>
              <div style={{display:'flex',gap:4,flexWrap:'wrap'}}>
                {row.targets.map(t=><span key={t} style={{fontSize:10.5,fontWeight:600,padding:'2px 6px',borderRadius:4,background:dark?'#1e293b':'#f1f5f9',color:textSec,border:`1px solid ${border}`}}>{t}</span>)}
              </div>
              <span style={{fontFamily:'IBM Plex Mono, monospace',fontSize:11.5,color:textSec}}>{row.top_match}</span>
              <div style={{display:'flex',alignItems:'center',gap:6}}>
                <div style={{width:7,height:7,borderRadius:'50%',background:theme.dot,flexShrink:0}}/>
                <span style={{fontSize:12.5,fontWeight:700,color:theme.text,fontVariantNumeric:'tabular-nums'}}>{(row.top_score*100).toFixed(0)}%</span>
              </div>
              <span style={{fontSize:12,color:textMut,fontVariantNumeric:'tabular-nums',textAlign:'right'}}>#{row.n}</span>
            </div>
          );
        })}
      </div>
      <p style={{fontSize:11.5,color:textMut,margin:'12px 0 0',textAlign:'center'}}>Click any row to re-run the search · History retained for 90 days</p>
    </div>
  );
}

// ── Admin ───────────────────────────────────────────────────────────────────
function UserTable({ users, dark, authToken, onRefresh }) {
  const cardBg=dark?'#111827':'#ffffff', border=dark?'#1e293b':'#e2e8f0';
  const textPri=dark?'#f1f5f9':'#111827', textSec=dark?'#94a3b8':'#64748b', textMut=dark?'#475569':'#94a3b8';
  const [hov,setHov]=React.useState(null);
  const [deleting,setDeleting]=React.useState(null);
  const handleDelete=async(userId)=>{
    if(!window.confirm(`Delete user ${userId}? This cannot be undone.`)) return;
    setDeleting(userId);
    try {
      const resp=await fetch(`/api/admin/users/${encodeURIComponent(userId)}`,{method:'DELETE',headers:{'Authorization':`Bearer ${authToken}`}});
      if(resp.ok) onRefresh&&onRefresh(); else alert('Failed to delete user.');
    } catch(_){alert('Error deleting user.');}
    setDeleting(null);
  };
  const statusBadge=(s)=>{
    const cfg={active:{bg:dark?'#14532d':'#dcfce7',text:dark?'#4ade80':'#15803d',label:'Active'},locked:{bg:dark?'#450a0a':'#fee2e2',text:dark?'#f87171':'#b91c1c',label:'Locked'},invited:{bg:dark?'#1e3a5f':'#dbeafe',text:dark?'#60a5fa':'#1e40af',label:'Invited'}};
    const c=cfg[s]||cfg.active;
    return <span style={{fontSize:11,fontWeight:600,padding:'2px 7px',borderRadius:4,background:c.bg,color:c.text}}>{c.label}</span>;
  };
  return (
    <div style={{background:cardBg,border:`1px solid ${border}`,borderRadius:10,overflow:'hidden',boxShadow:dark?'none':'0 1px 4px rgba(0,0,0,0.04)'}}>
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr 160px 130px 90px 70px 44px',padding:'10px 20px',background:dark?'#0f172a':'#f8fafc',borderBottom:`1px solid ${border}`}}>
        {['User','Email','Searches','Databases','Dir','Status',''].map(h=><span key={h} style={{fontSize:11,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.06em',color:textMut}}>{h}</span>)}
      </div>
      {users.map((u,i)=>{
        const pct=u.used/u.limit, barColor=pct>=1?'#dc2626':pct>=0.8?'#d97706':'#1855d4';
        return (
          <div key={u.id} onMouseEnter={()=>setHov(u.id)} onMouseLeave={()=>setHov(null)}
            style={{display:'grid',gridTemplateColumns:'1fr 1fr 160px 130px 90px 70px 44px',padding:'12px 20px',alignItems:'center',borderBottom:i<users.length-1?`1px solid ${border}`:'none',background:hov===u.id?(dark?'#1e293b':'#f8fafc'):'transparent',transition:'background 0.12s'}}>
            <div style={{display:'flex',alignItems:'center',gap:9}}>
              <div style={{width:28,height:28,borderRadius:'50%',flexShrink:0,background:dark?'#1e293b':'#f1f5f9',border:`1px solid ${border}`,display:'flex',alignItems:'center',justifyContent:'center',fontSize:11,fontWeight:700,color:dark?'#94a3b8':'#64748b'}}>
                {u.name.split(' ').map(p=>p[0]).join('')}
              </div>
              <div>
                <div style={{fontSize:13,fontWeight:600,color:textPri}}>{u.name}</div>
                <div style={{fontSize:11,color:textMut}}>{u.last}</div>
              </div>
            </div>
            <span style={{fontSize:12,color:textSec}}>{u.email}</span>
            <div>
              <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:4}}>
                <span style={{fontSize:11.5,fontWeight:600,color:pct>=1?'#dc2626':pct>=0.8?'#d97706':textPri,fontVariantNumeric:'tabular-nums'}}>{u.used} / {u.limit}</span>
                <span style={{fontSize:10.5,color:textMut}}>{Math.round(pct*100)}%</span>
              </div>
              <div style={{height:4,borderRadius:2,background:dark?'#334155':'#e2e8f0',overflow:'hidden'}}>
                <div style={{width:`${Math.min(100,pct*100)}%`,height:'100%',borderRadius:2,background:barColor}}/>
              </div>
            </div>
            <div style={{display:'flex',gap:3,flexWrap:'wrap'}}>
              {u.dbs.map(db=><span key={db} style={{fontSize:10.5,fontWeight:600,padding:'1px 5px',borderRadius:3,background:dark?'#1e293b':'#f1f5f9',color:textSec,border:`1px solid ${border}`,textTransform:'capitalize'}}>{db}</span>)}
            </div>
            <span style={{fontSize:11.5,color:u.dir==='bidirectional'?(dark?'#a78bfa':'#7c3aed'):textSec,fontWeight:u.dir==='bidirectional'?600:400}}>
              {u.dir==='bidirectional'?'⇄ Bidirectional':'→ Source only'}
            </span>
            {statusBadge(u.status)}
            <button onClick={()=>handleDelete(u.id)} disabled={deleting===u.id}
              style={{background:'transparent',border:'none',cursor:'pointer',color:dark?'#475569':'#94a3b8',padding:4,display:'flex',alignItems:'center',justifyContent:'center',borderRadius:4}}
              onMouseEnter={e=>e.currentTarget.style.color='#dc2626'}
              onMouseLeave={e=>e.currentTarget.style.color=dark?'#475569':'#94a3b8'}
              title="Delete user">
              <svg width={13} height={13} viewBox="0 0 13 13" fill="none"><path d="M2 3h9M5 3V2h3v1M10 3l-.7 8H3.7L3 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>
          </div>
        );
      })}
    </div>
  );
}

function AnalyticsTab({ dark }) {
  const cardBg=dark?'#111827':'#ffffff', border=dark?'#1e293b':'#e2e8f0';
  const textPri=dark?'#f1f5f9':'#111827', textSec=dark?'#94a3b8':'#64748b', textMut=dark?'#475569':'#94a3b8';
  const topParts=[{part:'8.KIS40.1342.1024',count:14},{part:'8.K58I.5534.1024',count:9},{part:'8.KIS40.1271.0500',count:8},{part:'8.K80I.3311.1024',count:6},{part:'8.KIH40.4422.1000',count:4}];
  const flows=[{src:'Kübler',tgt:'EPC',count:28,pct:55},{src:'Kübler',tgt:'Sick',count:15,pct:29},{src:'Kübler',tgt:'Both',count:8,pct:16}];
  const sc=(label,value,sub,color)=>(
    <div style={{background:cardBg,border:`1px solid ${border}`,borderRadius:10,padding:'16px 20px',flex:1}}>
      <div style={{fontSize:11,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.06em',color:textMut,marginBottom:8}}>{label}</div>
      <div style={{fontSize:28,fontWeight:700,color:color||textPri,letterSpacing:'-0.02em',marginBottom:2}}>{value}</div>
      <div style={{fontSize:12,color:textSec}}>{sub}</div>
    </div>
  );
  return (
    <div style={{display:'flex',flexDirection:'column',gap:20}}>
      <div style={{display:'flex',gap:14}}>
        {sc('Searches this month','51','↑ 18% vs last month','#1855d4')}
        {sc('Active users','5 / 6','1 user locked','#15803d')}
        {sc('Avg. top score','85.4%','Across all searches','#d97706')}
        {sc('Most used target','EPC','28 searches',null)}
      </div>
      <div style={{display:'flex',gap:14}}>
        <div style={{flex:1,background:cardBg,border:`1px solid ${border}`,borderRadius:10,padding:'16px 20px'}}>
          <div style={{fontSize:13,fontWeight:700,color:textPri,marginBottom:14}}>Top Searched Parts</div>
          {topParts.map((p,i)=>(
            <div key={p.part} style={{display:'flex',alignItems:'center',gap:10,padding:'7px 0',borderBottom:i<topParts.length-1?`1px solid ${border}`:'none'}}>
              <span style={{fontSize:11,fontWeight:700,color:textMut,width:16,flexShrink:0}}>{i+1}</span>
              <span style={{fontFamily:'IBM Plex Mono, monospace',fontSize:12,color:textPri,flex:1}}>{p.part}</span>
              <div style={{width:80,height:4,borderRadius:2,background:dark?'#334155':'#e2e8f0',overflow:'hidden'}}><div style={{width:`${(p.count/topParts[0].count)*100}%`,height:'100%',background:'#1855d4',borderRadius:2}}/></div>
              <span style={{fontSize:12,fontWeight:600,color:textSec,width:28,textAlign:'right',fontVariantNumeric:'tabular-nums'}}>{p.count}×</span>
            </div>
          ))}
        </div>
        <div style={{width:260,background:cardBg,border:`1px solid ${border}`,borderRadius:10,padding:'16px 20px'}}>
          <div style={{fontSize:13,fontWeight:700,color:textPri,marginBottom:14}}>Search Flows</div>
          {flows.map(f=>(
            <div key={f.tgt} style={{marginBottom:12}}>
              <div style={{display:'flex',justifyContent:'space-between',marginBottom:4,alignItems:'center'}}>
                <span style={{fontSize:12,color:textSec}}><span style={{fontWeight:600,color:textPri}}>Kübler</span><span style={{margin:'0 5px',color:textMut}}>→</span><span style={{fontWeight:600,color:dark?'#60a5fa':'#1855d4'}}>{f.tgt}</span></span>
                <span style={{fontSize:12,fontWeight:600,color:textSec,fontVariantNumeric:'tabular-nums'}}>{f.count} ({f.pct}%)</span>
              </div>
              <div style={{height:5,borderRadius:3,background:dark?'#334155':'#e2e8f0',overflow:'hidden'}}><div style={{width:`${f.pct}%`,height:'100%',borderRadius:3,background:'#1855d4'}}/></div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function AddUserModal({ onClose, dark, authToken, onCreated }) {
  const ALL_MFRS=['kubler','epc','sick','posital'];
  const [form,setForm]=React.useState({name:'',email:'',password:'',client:'posital',sources:[],limit:50});
  const [saving,setSaving]=React.useState(false);
  const [error,setError]=React.useState('');
  const cardBg=dark?'#111827':'#ffffff', border=dark?'#1e293b':'#e2e8f0';
  const textPri=dark?'#f1f5f9':'#111827', textSec=dark?'#94a3b8':'#64748b', inputBg=dark?'#0f172a':'#f8fafc';
  const iStyle={width:'100%',boxSizing:'border-box',padding:'9px 10px',background:inputBg,border:`1px solid ${border}`,borderRadius:6,color:textPri,fontFamily:'IBM Plex Sans, sans-serif',fontSize:13,outline:'none'};
  const lStyle={display:'block',fontSize:11,fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:textSec,marginBottom:5};
  const availSrc=ALL_MFRS.filter(m=>m!==form.client);
  const toggleSrc=(m)=>setForm(f=>({...f,sources:f.sources.includes(m)?f.sources.filter(x=>x!==m):[...f.sources,m]}));
  return (
    <div style={{position:'fixed',inset:0,background:'rgba(0,0,0,0.6)',zIndex:100,display:'flex',alignItems:'center',justifyContent:'center',backdropFilter:'blur(4px)'}} onClick={e=>e.target===e.currentTarget&&onClose()}>
      <div style={{background:cardBg,border:`1px solid ${border}`,borderRadius:12,width:480,maxHeight:'85vh',overflow:'auto',boxShadow:'0 24px 60px rgba(0,0,0,0.25)'}}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'18px 22px 14px',borderBottom:`1px solid ${border}`}}>
          <div>
            <div style={{fontSize:15,fontWeight:700,color:textPri}}>Add User</div>
            <div style={{fontSize:12,color:textSec,marginTop:2}}>Account is active immediately — share credentials directly</div>
          </div>
          <button onClick={onClose} style={{background:'none',border:'none',cursor:'pointer',color:textSec,display:'flex',padding:4}}>
            <svg width={16} height={16} viewBox="0 0 16 16" fill="none"><path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>
          </button>
        </div>
        <div style={{padding:'20px 22px',display:'flex',flexDirection:'column',gap:16}}>
          {error&&<div style={{background:'#fef2f2',border:'1px solid #fecaca',borderRadius:6,padding:'8px 12px',fontSize:12.5,color:'#b91c1c'}}>{error}</div>}
          <div style={{display:'flex',gap:12}}>
            <div style={{flex:1}}><label style={lStyle}>Full name</label><input style={iStyle} value={form.name} onChange={e=>setForm(f=>({...f,name:e.target.value}))} placeholder="Jane Smith" onFocus={e=>e.target.style.borderColor='#1855d4'} onBlur={e=>e.target.style.borderColor=border}/></div>
            <div style={{flex:1}}><label style={lStyle}>Work email</label><input style={iStyle} type="email" value={form.email} onChange={e=>setForm(f=>({...f,email:e.target.value}))} placeholder="j.smith@posital.com" onFocus={e=>e.target.style.borderColor='#1855d4'} onBlur={e=>e.target.style.borderColor=border}/></div>
          </div>
          <div><label style={lStyle}>Password</label><input style={iStyle} type="password" value={form.password} onChange={e=>setForm(f=>({...f,password:e.target.value}))} placeholder="Set a password for this user" onFocus={e=>e.target.style.borderColor='#1855d4'} onBlur={e=>e.target.style.borderColor=border}/></div>
          <div>
            <label style={lStyle}>Client — locked target</label>
            <select value={form.client} onChange={e=>setForm(f=>({...f,client:e.target.value,sources:f.sources.filter(m=>m!==e.target.value)}))} style={{...iStyle,cursor:'pointer'}}>
              {ALL_MFRS.map(m=><option key={m} value={m}>{MFR_LABELS[m]}</option>)}
            </select>
            <div style={{fontSize:11,color:dark?'#475569':'#94a3b8',marginTop:4}}>This is the locked search target — user can only find {MFR_LABELS[form.client]} replacements</div>
          </div>
          <div>
            <label style={lStyle}>Allowed source pool</label>
            <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
              {availSrc.map(m=>(
                <label key={m} style={{display:'flex',alignItems:'center',gap:6,cursor:'pointer',padding:'7px 14px',borderRadius:6,flex:1,justifyContent:'center',background:form.sources.includes(m)?(dark?'#1e3a5f':'#eff6ff'):(dark?'#0f172a':'#f8fafc'),border:`1px solid ${form.sources.includes(m)?(dark?'#1e40af':'#bfdbfe'):border}`}}>
                  <input type="checkbox" checked={form.sources.includes(m)} onChange={()=>toggleSrc(m)} style={{display:'none'}}/>
                  <span style={{fontSize:13,fontWeight:600,color:form.sources.includes(m)?(dark?'#60a5fa':'#1855d4'):textSec}}>{MFR_LABELS[m]}</span>
                </label>
              ))}
            </div>
            <div style={{fontSize:11,color:dark?'#475569':'#94a3b8',marginTop:4}}>User can only query encoders from these manufacturers</div>
          </div>
          <div>
            <label style={lStyle}>Daily search limit</label>
            <div style={{display:'flex',alignItems:'center',gap:10}}>
              <input type="range" min={1} max={100} step={1} value={form.limit} onChange={e=>setForm(f=>({...f,limit:+e.target.value}))} style={{flex:1,WebkitAppearance:'none',appearance:'none',height:4,borderRadius:2,background:'#334155',outline:'none',cursor:'pointer',accentColor:'#1855d4'}}/>
              <span style={{fontSize:13,fontWeight:700,color:textPri,width:36,textAlign:'right',fontVariantNumeric:'tabular-nums'}}>{form.limit}</span>
            </div>
          </div>
        </div>
        <div style={{display:'flex',gap:10,padding:'14px 22px 20px',borderTop:`1px solid ${border}`}}>
          <button onClick={onClose} style={{flex:1,padding:'9px',background:'transparent',border:`1px solid ${border}`,borderRadius:7,cursor:'pointer',fontFamily:'IBM Plex Sans, sans-serif',fontSize:13,fontWeight:600,color:textSec}}>Cancel</button>
          <button onClick={async()=>{
            setError('');
            if(!form.name||!form.email||!form.password){setError('Name, email and password are required.');return;}
            if(form.sources.length===0){setError('Select at least one source manufacturer.');return;}
            setSaving(true);
            try {
              const resp=await fetch('/api/admin/users',{method:'POST',headers:{'Content-Type':'application/json','Authorization':`Bearer ${authToken}`},
                body:JSON.stringify({name:form.name,email:form.email,password:form.password,client:form.client,searches_limit:form.limit,allowed_sources:form.sources,allowed_targets:[form.client],direction:'source_only'})});
              const data=await resp.json();
              if(!resp.ok){setError(data.detail||'Failed to create user.');setSaving(false);return;}
              onCreated&&onCreated(); onClose();
            } catch(e){setError('Could not reach server.');setSaving(false);}
          }} disabled={saving} style={{flex:2,padding:'9px',background:saving?'#bfdbfe':'#1855d4',border:'none',borderRadius:7,cursor:saving?'default':'pointer',fontFamily:'IBM Plex Sans, sans-serif',fontSize:13,fontWeight:600,color:'white'}}>
            {saving?'Creating…':'Create User'}
          </button>
        </div>
      </div>
    </div>
  );
}

function AdminPage({ dark, authToken }) {
  const [tab,setTab]=React.useState('users');
  const [showModal,setShowModal]=React.useState(false);
  const [users,setUsers]=React.useState([]);
  const bg=dark?'#0a0f1a':'#f4f6fa', cardBg=dark?'#111827':'#ffffff', border=dark?'#1e293b':'#e2e8f0';
  const textPri=dark?'#f1f5f9':'#111827', textSec=dark?'#94a3b8':'#64748b';
  const fetchUsers=React.useCallback(async()=>{
    if(!authToken||API_MODE!=='live') return;
    try {
      const resp=await fetch('/api/admin/users',{headers:{'Authorization':`Bearer ${authToken}`}});
      if(!resp.ok) return;
      const data=await resp.json();
      const mapped=(data.users||[]).map(u=>({
        id:u.userId, name:u.name||u.userId, email:u.userId,
        used:u.searches_used||0, limit:u.searches_limit||0,
        sources:(u.allowed_sources||[]), dbs:(u.allowed_targets||[]),
        client:u.client||'', dir:u.direction||'source_only',
        status:u.status||'active', last:u.last_search_date||'—',
      }));
      setUsers(mapped);
    } catch(_){}
  },[authToken]);
  React.useEffect(()=>{fetchUsers();},[fetchUsers]);
  const tabStyle=(id)=>({padding:'8px 16px',borderRadius:6,cursor:'pointer',fontFamily:'IBM Plex Sans, sans-serif',fontSize:13,fontWeight:600,border:'none',background:tab===id?(dark?'#1e293b':'#ffffff'):'transparent',color:tab===id?(dark?'#f1f5f9':'#111827'):textSec,boxShadow:tab===id?(dark?'none':'0 1px 3px rgba(0,0,0,0.08)'):'none'});
  return (
    <div style={{flex:1,background:bg,overflowY:'auto',padding:'24px 28px'}}>
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:20}}>
        <div>
          <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:2}}>
            <span style={{fontFamily:'IBM Plex Mono, monospace',fontSize:13,fontWeight:700,color:'#1a3570',letterSpacing:'0.02em'}}>aqb</span>
            <span style={{fontSize:11,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.06em',color:dark?'#475569':'#94a3b8'}}>Admin Console</span>
          </div>
          <h2 style={{margin:0,fontSize:18,fontWeight:700,color:textPri,letterSpacing:'-0.02em'}}>Client Management</h2>
          <p style={{margin:'3px 0 0',fontSize:13,color:textSec}}>AQB Solutions · {users.length} user{users.length!==1?'s':''} across all clients</p>
        </div>
        {tab==='users'&&<button onClick={()=>setShowModal(true)} style={{display:'flex',alignItems:'center',gap:6,padding:'8px 14px',borderRadius:7,background:'#1855d4',color:'white',border:'none',fontFamily:'IBM Plex Sans, sans-serif',fontSize:13,fontWeight:600,cursor:'pointer'}}>
          <svg width={13} height={13} viewBox="0 0 13 13" fill="none"><path d="M6.5 1v11M1 6.5h11" stroke="white" strokeWidth="1.8" strokeLinecap="round"/></svg>
          Add User
        </button>}
      </div>
      <div style={{display:'flex',gap:4,background:dark?'#0f172a':'#f1f5f9',padding:4,borderRadius:8,width:'fit-content',marginBottom:20,border:`1px solid ${border}`}}>
        <button style={tabStyle('users')} onClick={()=>setTab('users')}>User Management</button>
        <button style={tabStyle('analytics')} onClick={()=>setTab('analytics')}>Usage Analytics</button>
      </div>
      {tab==='users'&&<UserTable users={users} dark={dark} authToken={authToken} onRefresh={fetchUsers}/>}
      {tab==='analytics'&&<AnalyticsTab dark={dark}/>}
      {showModal&&<AddUserModal onClose={()=>setShowModal(false)} dark={dark} authToken={authToken} onCreated={fetchUsers}/>}
    </div>
  );
}

// ── Tweaks Panel (simplified) ───────────────────────────────────────────────
function TweaksPanel({ tweaks, setTweak, children }) {
  const [open,setOpen]=React.useState(false);
  return (
    <>
      <button onClick={()=>setOpen(o=>!o)} style={{position:'fixed',bottom:20,right:20,zIndex:200,width:36,height:36,borderRadius:'50%',background:'#1855d4',border:'none',cursor:'pointer',display:'flex',alignItems:'center',justifyContent:'center',boxShadow:'0 2px 8px rgba(0,0,0,0.3)'}}>
        <svg width={16} height={16} viewBox="0 0 16 16" fill="none">
          <circle cx="8" cy="8" r="3" stroke="white" strokeWidth="1.4"/>
          <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.42 1.42M11.53 11.53l1.42 1.42M3.05 12.95l1.42-1.42M11.53 4.47l1.42-1.42" stroke="white" strokeWidth="1.4" strokeLinecap="round"/>
        </svg>
      </button>
      {open&&(
        <div style={{position:'fixed',bottom:66,right:20,zIndex:200,background:'#0f172a',border:'1px solid #1e293b',borderRadius:10,padding:'16px',width:220,boxShadow:'0 8px 24px rgba(0,0,0,0.4)',fontFamily:'IBM Plex Sans, sans-serif'}}>
          <div style={{fontSize:11,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.08em',color:'#475569',marginBottom:12}}>Tweaks</div>
          {children}
        </div>
      )}
    </>
  );
}

function TweakSection({ title, children }) {
  return (
    <div style={{marginBottom:12}}>
      <div style={{fontSize:10,fontWeight:600,textTransform:'uppercase',letterSpacing:'0.06em',color:'#334155',marginBottom:8}}>{title}</div>
      {children}
    </div>
  );
}

function TweakRadio({ id, label, options, tweaks, setTweak }) {
  return (
    <div style={{marginBottom:8}}>
      <div style={{fontSize:11,color:'#64748b',marginBottom:5}}>{label}</div>
      <div style={{display:'flex',gap:4}}>
        {options.map(o=>(
          <button key={o.value} onClick={()=>setTweak(id,o.value)} style={{flex:1,padding:'4px 0',fontSize:11.5,fontWeight:600,background:tweaks[id]===o.value?'#1855d4':'transparent',color:tweaks[id]===o.value?'white':'#64748b',border:`1px solid ${tweaks[id]===o.value?'#1855d4':'#334155'}`,borderRadius:4,cursor:'pointer',fontFamily:'IBM Plex Sans, sans-serif'}}>
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function TweakSlider({ id, label, min, max, step, tweaks, setTweak }) {
  return (
    <div style={{marginBottom:8}}>
      <div style={{display:'flex',justifyContent:'space-between',marginBottom:4}}>
        <span style={{fontSize:11,color:'#64748b'}}>{label}</span>
        <span style={{fontSize:11,fontWeight:600,color:'#94a3b8'}}>{tweaks[id]}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={tweaks[id]} onChange={e=>setTweak(id,+e.target.value)} style={{width:'100%',WebkitAppearance:'none',appearance:'none',height:4,borderRadius:2,background:'#334155',outline:'none',cursor:'pointer'}}/>
    </div>
  );
}

// ── App ─────────────────────────────────────────────────────────────────────
// ── Error Boundary — catches React render crashes and shows error instead of white screen
class ErrorBoundary extends React.Component {
  constructor(props){ super(props); this.state={hasError:false,error:null}; }
  static getDerivedStateFromError(error){ return {hasError:true,error}; }
  componentDidCatch(error,info){ console.error('React crash:',error,info); }
  render(){
    if(this.state.hasError){
      return (
        <div style={{padding:40,fontFamily:'IBM Plex Sans, sans-serif',color:'#111827'}}>
          <div style={{fontSize:16,fontWeight:700,color:'#b91c1c',marginBottom:8}}>Something went wrong rendering results</div>
          <div style={{fontFamily:'IBM Plex Mono, monospace',fontSize:12,color:'#64748b',whiteSpace:'pre-wrap',background:'#f8fafc',padding:12,borderRadius:6,border:'1px solid #e2e8f0'}}>
            {this.state.error?.message}
          </div>
          <button onClick={()=>this.setState({hasError:false,error:null})} style={{marginTop:12,padding:'6px 14px',background:'#1855d4',color:'white',border:'none',borderRadius:6,cursor:'pointer',fontFamily:'IBM Plex Sans, sans-serif',fontSize:13}}>
            Dismiss
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}


// ── WeightsPage ──────────────────────────────────────────────────────────────
function WeightsPage({ dark, t2Raw, t3Raw, setT2Raw, setT3Raw }) {
  const [toast,setToast]=React.useState(false);
  const showToast=()=>{setToast(true);setTimeout(()=>setToast(false),2500);};
  const bg=dark?'#0a0f1a':'#f4f6fa', cardBg=dark?'#111827':'#ffffff';
  const border=dark?'#1e293b':'#e2e8f0', textPri=dark?'#f1f5f9':'#111827';
  const textSec=dark?'#94a3b8':'#64748b', textMut=dark?'#475569':'#94a3b8';

  const T2_PARAMS = [
    {field:'cpr_values',         label:'PPR Coverage',      weight:'0.30'},
    {field:'ip_rating',          label:'IP Rating',          weight:'0.20'},
    {field:'connection_type_canonical', label:'Connection Type', weight:'0.15'},
    {field:'output_circuit_canonical',  label:'Output Circuit',  weight:'0.15'},
    {field:'housing_diameter_mm',label:'Housing Diameter',   weight:'0.10'},
    {field:'shaft_bore_diameter_mm',label:'Bore Diameter',   weight:'0.10'},
  ];
  const T3_PARAMS = [
    {field:'supply_voltage',     label:'Supply Voltage',     weight:'0.25'},
    {field:'sensing_method',     label:'Sensing Method',     weight:'0.20'},
    {field:'operating_temp_max_c',label:'Max Operating Temp',weight:'0.15'},
    {field:'shock_resistance_ms2',label:'Shock Resistance',  weight:'0.15'},
    {field:'shaft_load_radial_n',label:'Shaft Load',         weight:'0.10'},
    {field:'vibration_resistance_ms2',label:'Vibration',     weight:'0.10'},
    {field:'connector_pins',     label:'Connector Pins',     weight:'0.05'},
  ];

  const SliderRow=({field,label,defaultWeight,raw,setRaw})=>{
    const val=raw[field]??5;
    const pct=((val/Object.values(raw).reduce((s,v)=>s+v,0))*100).toFixed(1);
    return (
      <div style={{marginBottom:14}}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:4}}>
          <span style={{fontSize:12.5,color:textPri,fontWeight:500}}>{label}</span>
          <div style={{display:'flex',alignItems:'center',gap:8}}>
            <span style={{fontSize:11,color:textMut,fontVariantNumeric:'tabular-nums'}}>({pct}%)</span>
            <span style={{fontSize:13,fontWeight:700,color:dark?'#60a5fa':'#1a3570',
              minWidth:18,textAlign:'right',fontVariantNumeric:'tabular-nums'}}>{val}</span>
          </div>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:8}}>
          <span style={{fontSize:10,color:textMut,minWidth:8}}>1</span>
          <input type="range" min={1} max={10} step={1} value={val}
            onChange={e=>setRaw(r=>({...r,[field]:parseInt(e.target.value)}))}
            style={{flex:1,WebkitAppearance:'none',appearance:'none',height:4,
              borderRadius:2,background:dark?'#334155':'#e2e8f0',
              outline:'none',cursor:'pointer',accentColor:'#1a3570'}}/>
          <span style={{fontSize:10,color:textMut,minWidth:16}}>10</span>
        </div>
      </div>
    );
  };

  const Section=({title,subtitle,badge,params,raw,setRaw})=>(
    <div style={{background:cardBg,border:`1px solid ${border}`,borderRadius:10,padding:'20px 24px',marginBottom:16}}>
      <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:4}}>
        <span style={{fontSize:14,fontWeight:700,color:textPri}}>{title}</span>
        <span style={{fontSize:10,fontWeight:700,background:badge==='T2'?'#1e3a5f':'#1a3a1a',
          color:badge==='T2'?'#60a5fa':'#4ade80',
          padding:'2px 6px',borderRadius:3,letterSpacing:'0.05em'}}>{badge}</span>
      </div>
      <div style={{fontSize:11.5,color:textSec,marginBottom:16}}>{subtitle}</div>
      {params.map(p=><SliderRow key={p.field} field={p.field} label={p.label}
        defaultWeight={p.weight} raw={raw} setRaw={setRaw}/>)}
    </div>
  );

  return (
    <div style={{flex:1,background:bg,overflowY:'auto',padding:'24px 32px'}}>
      <div style={{maxWidth:680,margin:'0 auto'}}>
        <div style={{display:'flex',alignItems:'flex-start',justifyContent:'space-between',marginBottom:24,gap:12}}>
          <div>
            <h2 style={{fontSize:20,fontWeight:700,color:textPri,marginBottom:6}}>Scoring Weights</h2>
            <p style={{fontSize:13,color:textSec,lineHeight:1.6}}>
              Adjust how each parameter contributes to the match score. Sliders use integers 1–10;
              weights are normalised automatically before scoring. Changes apply to your next search.
            </p>
          </div>
          <div style={{display:'flex',gap:8,flexShrink:0,marginTop:4}}>
            <button onClick={()=>{setT2Raw({...DEFAULT_T2_WEIGHTS});setT3Raw({...DEFAULT_T3_WEIGHTS});}}
              style={{padding:'8px 14px',background:'transparent',border:`1px solid ${border}`,
                borderRadius:7,cursor:'pointer',fontFamily:'IBM Plex Sans, sans-serif',
                fontSize:12.5,fontWeight:500,color:textSec,whiteSpace:'nowrap'}}>
              Reset to defaults
            </button>
            <button onClick={showToast}
              style={{padding:'8px 16px',background:'#1a3570',border:'none',
                borderRadius:7,cursor:'pointer',fontFamily:'IBM Plex Sans, sans-serif',
                fontSize:12.5,fontWeight:600,color:'#ffffff',whiteSpace:'nowrap'}}>
              Apply Weights
            </button>
          </div>
        </div>

        {/* ── Tier 1 — Hard Stops (locked) ── */}
        <div style={{background:cardBg,border:`1px solid ${border}`,borderRadius:10,padding:'20px 24px',marginBottom:16,opacity:0.75}}>
          <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:12}}>
            <span style={{fontSize:14,fontWeight:700,color:textPri}}>Hard Stops</span>
            <span style={{fontSize:10,fontWeight:700,background:dark?'#3b1f1f':'#fef2f2',
              color:dark?'#fca5a5':'#b91c1c',
              padding:'2px 6px',borderRadius:3,letterSpacing:'0.05em'}}>T1</span>
            <span style={{marginLeft:'auto',display:'flex',alignItems:'center',gap:5,fontSize:11,fontWeight:600,color:textSec}}>
              <svg width={12} height={12} viewBox="0 0 12 12" fill="none">
                <rect x="2" y="5" width="8" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.3"/>
                <path d="M4 5V3.5a2 2 0 1 1 4 0V5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
              </svg>
              Locked
            </span>
          </div>

          {/* CR note */}
          <div style={{display:'flex',alignItems:'flex-start',gap:8,background:dark?'#2d1f0a':'#fffbeb',
            border:`1px solid ${dark?'#78350f':'#fcd34d'}`,borderRadius:6,padding:'8px 12px',marginBottom:16}}>
            <svg width={14} height={14} viewBox="0 0 14 14" fill="none" style={{flexShrink:0,marginTop:1}}>
              <path d="M7 1.5L12.5 11H1.5L7 1.5Z" stroke={dark?'#fbbf24':'#d97706'} strokeWidth="1.3" strokeLinejoin="round"/>
              <path d="M7 5.5v3M7 10h.01" stroke={dark?'#fbbf24':'#d97706'} strokeWidth="1.3" strokeLinecap="round"/>
            </svg>
            <span style={{fontSize:11.5,color:dark?'#fbbf24':'#92400e',lineHeight:1.5}}>
              Any changes to Tier 1 parameters require a CR ticket to be raised.
            </span>
          </div>

          {/* Locked parameter rows */}
          {[
            {label:'Shaft Type',             rule:'Exact Match'},
            {label:'Bore Diameter (Hollow)', rule:'Exact Match'},
            {label:'Output Voltage Class',   rule:'Forbidden Pairs'},
          ].map(({label,rule})=>(
            <div key={label} style={{display:'flex',alignItems:'center',gap:10,marginBottom:12,
              padding:'8px 12px',borderRadius:6,background:dark?'#0f172a':'#f8fafc',
              border:`1px solid ${border}`}}>
              <svg width={12} height={12} viewBox="0 0 12 12" fill="none" style={{flexShrink:0}}>
                <rect x="2" y="5" width="8" height="6" rx="1.5" stroke={textSec} strokeWidth="1.2"/>
                <path d="M4 5V3.5a2 2 0 1 1 4 0V5" stroke={textSec} strokeWidth="1.2" strokeLinecap="round"/>
              </svg>
              <span style={{fontSize:12.5,color:textSec,fontWeight:500,flex:1}}>{label}</span>
              <span style={{fontSize:10.5,fontWeight:600,color:dark?'#fca5a5':'#b91c1c',
                background:dark?'#3b1f1f':'#fef2f2',padding:'2px 8px',borderRadius:4,
                letterSpacing:'0.03em',whiteSpace:'nowrap'}}>
                {rule}
              </span>
            </div>
          ))}
        </div>

        <Section title="Physical Match" subtitle="T2 parameters — weighted 70% of final score. These are hard physical compatibility factors." badge="T2"
          params={T2_PARAMS} raw={t2Raw} setRaw={setT2Raw}/>
        <Section title="Secondary Specs" subtitle="T3 parameters — weighted 30% of final score. Operational and environmental compatibility." badge="T3"
          params={T3_PARAMS} raw={t3Raw} setRaw={setT3Raw}/>

        {/* Toast confirmation */}
        {toast&&<div style={{position:'fixed',bottom:32,left:'50%',transform:'translateX(-50%)',
          background:dark?'#1e293b':'#1a3570',color:'#ffffff',
          padding:'10px 20px',borderRadius:8,fontSize:13,fontWeight:600,
          display:'flex',alignItems:'center',gap:8,boxShadow:'0 4px 16px rgba(0,0,0,0.18)',
          zIndex:9999,pointerEvents:'none',whiteSpace:'nowrap'}}>
          <svg width={15} height={15} viewBox="0 0 15 15" fill="none">
            <circle cx="7.5" cy="7.5" r="6.5" stroke="#4ade80" strokeWidth="1.4"/>
            <path d="M4.5 7.5l2 2 4-4" stroke="#4ade80" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          Weights applied — will take effect on your next search
        </div>}
      </div>
    </div>
  );
}

const TWEAK_DEFAULTS={colorMode:'light',userRole:'enduser',searchesUsed:53};

function App() {
  const [tweaks,setTweaksState]=React.useState(TWEAK_DEFAULTS);
  const setTweak=(id,val)=>setTweaksState(t=>({...t,[id]:val}));
  const [page,setPage]=React.useState('login');
  const [loggedInRole,setLoggedInRole]=React.useState('enduser');
  const [authToken,setAuthToken]=React.useState(null);
  const [liveUser,setLiveUser]=React.useState(null);
  const [sessionMsg,setSessionMsg]=React.useState('');
  const dark=tweaks.colorMode==='dark';

  const [t2Raw,setT2Raw]=React.useState({...DEFAULT_T2_WEIGHTS});
  const [t3Raw,setT3Raw]=React.useState({...DEFAULT_T3_WEIGHTS});

  // Lifted search state — survives tab navigation
  const [liveResults,setLiveResults]=React.useState(null);
  const [liveSource,setLiveSource]=React.useState(null);
  const [searchState,setSearchState]=React.useState('idle');
  const [expandedCards,setExpandedCards]=React.useState({});
  const [searchError,setSearchError]=React.useState(null);
  const [lastPartNum,setLastPartNum]=React.useState('');
  const [lastTopN,setLastTopN]=React.useState(5);
  const [lastElapsed,setLastElapsed]=React.useState(null);
  const [connectionType,setConnectionType]=React.useState(null);

  const handleLogout=React.useCallback((msg='')=>{
    setAuthToken(null); setLiveUser(null);
    setLoggedInRole('enduser'); setPage('login');
    if(msg) setSessionMsg(msg);
  },[]);

  // Auto-logout after 10 minutes of inactivity
  useIdleTimeout(React.useCallback(()=>handleLogout('You were logged out due to inactivity.'),[handleLogout]));
  // Single-session guard — polls /api/auth/me every 30s
  useSessionGuard(authToken, handleLogout);

  // In live mode, use real user data; in mock mode, use tweaks-driven mock
  const baseUser = (API_MODE==='live' && liveUser)
    ? liveUser
    : {...MOCK_DATA.user, searches_used:tweaks.searchesUsed, role:loggedInRole};

  const handleLogin=async(role, token, userData)=>{
    if (API_MODE==='live' && token) {
      setAuthToken(token);
      setLiveUser(userData);
      setLoggedInRole(userData.role);
      setPage(userData.role==='superadmin'?'admin':'search');
    } else {
      setLoggedInRole(role);
      setPage(role==='clientadmin'||role==='superadmin'?'admin':'search');
      setTweak('userRole',role);
    }
  };
  const appBg=dark?'#0a0f1a':'#f4f6fa';

  if (page==='login') return (
    <>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}*{box-sizing:border-box;margin:0;padding:0}html,body,#root{height:100%;overflow:hidden}body{font-family:'IBM Plex Sans',sans-serif;-webkit-font-smoothing:antialiased}`}</style>
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet"/>
      {sessionMsg&&(
        <div style={{position:'fixed',top:0,left:0,right:0,zIndex:9999,background:'#1e3a5f',color:'#e2e8f0',padding:'11px 20px',fontSize:13,textAlign:'center',display:'flex',alignItems:'center',justifyContent:'center',gap:10,boxShadow:'0 2px 8px rgba(0,0,0,0.3)'}}>
          <svg width={14} height={14} viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="6" stroke="#60a5fa" strokeWidth="1.3"/><path d="M7 4v3.5M7 9.5v.5" stroke="#60a5fa" strokeWidth="1.5" strokeLinecap="round"/></svg>
          {sessionMsg}
          <button onClick={()=>setSessionMsg('')} style={{marginLeft:8,background:'none',border:'none',color:'#94a3b8',cursor:'pointer',fontSize:18,lineHeight:1,padding:0}}>×</button>
        </div>
      )}
      <LoginPage onLogin={handleLogin} dark={dark}/>
      <TweaksPanel tweaks={tweaks} setTweak={setTweak}>
        <TweakSection title="Appearance"><TweakRadio id="colorMode" label="Mode" options={[{value:'light',label:'Light'},{value:'dark',label:'Dark'}]} tweaks={tweaks} setTweak={setTweak}/></TweakSection>
      </TweaksPanel>
    </>
  );

  return (
    <>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}*{box-sizing:border-box;margin:0;padding:0}html,body,#root{height:100%;overflow:hidden}body{font-family:'IBM Plex Sans',sans-serif;-webkit-font-smoothing:antialiased}::-webkit-scrollbar{width:6px;height:6px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:#334155;border-radius:3px}`}</style>
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet"/>
      <div style={{display:'flex',height:'100vh',overflow:'hidden',background:appBg,fontFamily:'IBM Plex Sans, sans-serif'}}>
        <AppNav page={page} setPage={setPage} user={baseUser} dark={dark} onLogout={handleLogout}/>
        <div style={{flex:1,display:'flex',flexDirection:'column',overflow:'hidden',minWidth:0}}>
          <div style={{height:44,flexShrink:0,background:dark?'#0f172a':'#ffffff',borderBottom:`1px solid ${dark?'#1e293b':'#e2e8f0'}`,display:'flex',alignItems:'center',padding:'0 20px',gap:8}}>
            <span style={{fontSize:12.5,fontWeight:600,color:dark?'#94a3b8':'#64748b'}}>
              {page==='search'&&'Cross-Reference Search'}{page==='history'&&'Search History'}{page==='admin'&&'Admin Console · AQB Solutions'}{page==='weights'&&'Scoring Weights'}
            </span>
            <div style={{marginLeft:'auto',display:'flex',alignItems:'center',gap:12}}>
              {/* One-click dark/light mode toggle */}
              <button
                onClick={()=>setTweak('colorMode',dark?'light':'dark')}
                title={dark?'Switch to light mode':'Switch to dark mode'}
                style={{width:36,height:36,borderRadius:7,background:'transparent',border:`1px solid ${dark?'#334155':'#e2e8f0'}`,cursor:'pointer',display:'flex',alignItems:'center',justifyContent:'center',color:dark?'#94a3b8':'#64748b',flexShrink:0}}
                onMouseEnter={e=>{e.currentTarget.style.background=dark?'#1e293b':'#f1f5f9';}}
                onMouseLeave={e=>{e.currentTarget.style.background='transparent';}}>
                {dark
                  ? <svg width={17} height={17} viewBox="0 0 14 14" fill="none"><circle cx="7" cy="7" r="3" stroke="currentColor" strokeWidth="1.3"/><path d="M7 1v1.5M7 11.5V13M1 7h1.5M11.5 7H13M2.93 2.93l1.06 1.06M10.01 10.01l1.06 1.06M2.93 11.07l1.06-1.06M10.01 3.99l1.06-1.06" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>
                  : <svg width={17} height={17} viewBox="0 0 14 14" fill="none"><path d="M11.5 9A5 5 0 015 2.5h-.5a5 5 0 100 9H5a5.02 5.02 0 006.5-2.5z" stroke="currentColor" strokeWidth="1.3" fill="none" strokeLinecap="round" strokeLinejoin="round"/></svg>
                }
              </button>
              <span style={{fontSize:10.5,fontWeight:700,textTransform:'uppercase',letterSpacing:'0.06em',padding:'2px 7px',borderRadius:4,background:dark?'#1e3a5f':'#eff6ff',color:dark?'#60a5fa':'#1a3570'}}>
                {(baseUser.role==='superadmin'||baseUser.role==='clientadmin')?'ADMIN':'END USER'}
              </span>
              {baseUser.role==='enduser'&&(()=>{
                const rem=baseUser.searches_limit-baseUser.searches_used, pct=rem/baseUser.searches_limit;
                return (
                  <div style={{display:'flex',alignItems:'center',gap:6}}>
                    <div style={{width:60,height:4,borderRadius:2,background:dark?'#334155':'#e2e8f0',overflow:'hidden'}}>
                      <div style={{width:`${Math.max(0,pct*100)}%`,height:'100%',borderRadius:2,background:pct<=0.1?'#dc2626':pct<=0.2?'#d97706':'#1a3570'}}/>
                    </div>
                    <span style={{fontSize:11.5,fontWeight:600,color:dark?'#64748b':'#94a3b8',fontVariantNumeric:'tabular-nums'}}>{rem}/{baseUser.searches_limit}</span>
                  </div>
                );
              })()}
            </div>
          </div>
          <div style={{flex:1,display:'flex',overflow:'hidden',minHeight:0}}>
            {page==='search'&&<SearchPage user={baseUser} dark={dark} authToken={authToken} setUser={setLiveUser} t2Raw={t2Raw} t3Raw={t3Raw}
              liveResults={liveResults} setLiveResults={setLiveResults}
              liveSource={liveSource} setLiveSource={setLiveSource}
              searchState={searchState} setSearchState={setSearchState}
              expandedCards={expandedCards} setExpandedCards={setExpandedCards}
              searchError={searchError} setSearchError={setSearchError}
              lastPartNum={lastPartNum} setLastPartNum={setLastPartNum}
              lastTopN={lastTopN} setLastTopN={setLastTopN}
              lastElapsed={lastElapsed} setLastElapsed={setLastElapsed}
              connectionType={connectionType} setConnectionType={setConnectionType}
            />}
            {page==='history'&&<HistoryPage user={baseUser} onRerun={()=>setPage('search')} dark={dark} authToken={authToken}/>}
            {page==='weights'&&<WeightsPage dark={dark} t2Raw={t2Raw} t3Raw={t3Raw} setT2Raw={setT2Raw} setT3Raw={setT3Raw}/>}
            {page==='admin'&&<AdminPage dark={dark} authToken={authToken}/>}
          </div>
        </div>
      </div>
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));