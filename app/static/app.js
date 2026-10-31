let currentRole = 'auxiliar';
let adminAuthenticated = false;
let pendingRoleTarget = null;
let mesasList = [];
let menuList = [];
let inventarioList = [];
let mesaActiva = null;
let ordenActivaDetalle = null;
let metodoPagoSeleccionado = 'efectivo';
let factorSimulacionActual = 1.0;
let mostrarPinsEnTabla = false;

let borradorPlatos = [{ numero_plato: 1, notas: '', items: {} }];
let platoActivoIndex = 0;
let borradorBebidas = {};

document.addEventListener('DOMContentLoaded', () => {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js').catch(() => {});
  }
  const todayStr = new Date().toISOString().split('T')[0];
  const dateInput = document.getElementById('import-fecha-input');
  if (dateInput) dateInput.value = todayStr;

  loadMesasAndMenu();
  loadHistorialDiaAuxiliar();
  refreshCocinaBadgeSilent();

  setInterval(() => {
    refreshCocinaBadgeSilent();
    if (currentRole === 'cocina') {
      loadColaCocina();
    } else if (currentRole === 'auxiliar') {
      refreshMesasSilent();
    } else if (currentRole === 'admin') {
      const statsPanel = document.getElementById('admin-panel-stats');
      const iaPanel = document.getElementById('admin-panel-ia');
      const statsVisible = statsPanel && !statsPanel.classList.contains('hidden');
      const iaVisible = iaPanel && !iaPanel.classList.contains('hidden');
      if (statsVisible || iaVisible) {
        loadAdminAnalytics();
      }
    }
  }, 3000);
});

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.remove();
  }, 3500);
}

async function refreshCocinaBadgeSilent() {
  try {
    const res = await fetch('/api/pos/cocina/cola');
    if (!res.ok) return;
    const data = await res.json();
    const badge = document.getElementById('nav-cocina-badge');
    if (badge) {
      badge.textContent = data.total_ordenes_pendientes || 0;
    }
  } catch (e) {}
}

function abrirModalPin(targetRole = null) {
  pendingRoleTarget = targetRole;
  const modal = document.getElementById('modal-pin');
  const input = document.getElementById('modal-pin-input');
  const titulo = document.getElementById('modal-pin-titulo');
  if (titulo) {
    titulo.textContent = targetRole === 'admin' ? 'Acceso a Administración' : 'Ingresar con PIN de Usuario';
  }
  if (input) {
    input.value = '';
  }
  if (modal) {
    modal.classList.remove('hidden');
    if (input) input.focus();
  }
}

function cerrarModalPin() {
  const modal = document.getElementById('modal-pin');
  if (modal) modal.classList.add('hidden');
  pendingRoleTarget = null;
}

async function confirmarModalPin() {
  const input = document.getElementById('modal-pin-input');
  const pin = (input ? input.value : '').trim();
  if (!pin) return;

  const payload = { pin };
  if (pendingRoleTarget) payload.rol = pendingRoleTarget;

  const res = await fetch('/api/pos/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    showToast('PIN incorrecto o sin permisos para este rol.', 'error');
    return;
  }

  const data = await res.json();
  if (data.rol === 'admin') {
    adminAuthenticated = true;
  }
  document.getElementById('sync-indicator').textContent = `${data.usuario} (${data.rol.toUpperCase()})`;
  const roleToActivate = pendingRoleTarget || data.rol;
  cerrarModalPin();
  switchRole(roleToActivate, true);
  showToast(`Sesión activa: ${data.usuario}`, 'success');
}

async function switchRole(role, skipPinPrompt = false) {
  if (role === 'admin' && !adminAuthenticated && !skipPinPrompt) {
    abrirModalPin('admin');
    return;
  }

  currentRole = role;
  document.querySelectorAll('.role-btn').forEach((b) => b.classList.remove('active'));
  const btn = document.getElementById(`btn-role-${role}`);
  if (btn) btn.classList.add('active');

  document.getElementById('view-auxiliar').classList.add('hidden');
  document.getElementById('view-cocina').classList.add('hidden');
  document.getElementById('view-admin').classList.add('hidden');
  document.getElementById(`view-${role}`).classList.remove('hidden');

  if (role === 'auxiliar') {
    loadMesasAndMenu();
    loadHistorialDiaAuxiliar();
  }
  if (role === 'cocina') loadColaCocina();
  if (role === 'admin') {
    loadAdminAnalytics();
    loadInventarioAdmin();
    loadMenuAndMesasAdmin();
    loadUsuariosAdmin();
  }
}

function switchAdminTab(tab) {
  ['stats', 'ia', 'inv', 'menu', 'users', 'import'].forEach((t) => {
    const panel = document.getElementById(`admin-panel-${t}`);
    if (panel) panel.classList.add('hidden');
    const btn = document.getElementById(`tab-admin-${t}`);
    if (btn) btn.classList.add('btn-secondary');
  });
  document.getElementById(`admin-panel-${tab}`).classList.remove('hidden');
  document.getElementById(`tab-admin-${tab}`).classList.remove('btn-secondary');

  if (tab === 'stats' || tab === 'ia') loadAdminAnalytics();
  if (tab === 'inv') loadInventarioAdmin();
  if (tab === 'menu') loadMenuAndMesasAdmin();
  if (tab === 'users') loadUsuariosAdmin();
}

async function loadMesasAndMenu() {
  try {
    const [resMesas, resMenu] = await Promise.all([
      fetch('/api/pos/mesas'),
      fetch('/api/pos/menu')
    ]);
    mesasList = await resMesas.json();
    menuList = await resMenu.json();

    if (!mesaActiva && mesasList.length > 0) {
      mesaActiva = mesasList[0];
      document.getElementById('orden-workspace').classList.remove('hidden');
      document.getElementById('mesa-seleccionada-titulo').textContent = `Mesa Seleccionada: ${mesaActiva.nombre}`;
      renderPlatosTabs();
      renderBorradorResumen();
      cargarCuentaAbiertaMesa();
    } else if (mesaActiva) {
      const updated = mesasList.find((m) => m.id === mesaActiva.id);
      if (updated) mesaActiva = updated;
    }

    renderMesas();
    renderMenuBotones();
  } catch (e) {}
}

async function refreshMesasSilent() {
  try {
    const res = await fetch('/api/pos/mesas');
    mesasList = await res.json();
    if (mesaActiva) {
      const updated = mesasList.find((m) => m.id === mesaActiva.id);
      if (updated) {
        const prevCocina = mesaActiva.estado_cocina;
        mesaActiva = updated;
        if (prevCocina !== updated.estado_cocina) {
          cargarCuentaAbiertaMesa();
        }
      }
    }
    renderMesas();
  } catch (e) {}
}

function renderMesas() {
  const container = document.getElementById('mesas-container');
  if (!container) return;
  container.innerHTML = mesasList.map((m) => {
    const isSel = mesaActiva && mesaActiva.id === m.id ? 'selected' : '';
    const statusText = m.estado === 'ocupada'
      ? `Ocupada | $${m.total_actual_pesos.toFixed(2)}`
      : 'Disponible';
    let cocinaTag = '';
    if (m.estado === 'ocupada' && m.estado_cocina) {
      const label = m.estado_cocina === 'preparando'
        ? 'En cocina'
        : m.estado_cocina === 'en_cola'
          ? 'En espera'
          : 'Lista';
      cocinaTag = `<span class="badge badge-info" style="font-size:0.68rem;">${label}</span>`;
    }
    return `
      <div class="mesa-card ${m.estado} ${isSel}" onclick="seleccionarMesa(${m.id})">
        <div class="mesa-name">
          <span>${m.nombre}</span>
          ${cocinaTag}
        </div>
        <div class="mesa-status">${statusText}</div>
      </div>
    `;
  }).join('');
}

async function seleccionarMesa(mesaId) {
  mesaActiva = mesasList.find((m) => m.id === mesaId);
  if (!mesaActiva) return;

  renderMesas();
  document.getElementById('orden-workspace').classList.remove('hidden');
  document.getElementById('mesa-seleccionada-titulo').textContent = `Mesa Seleccionada: ${mesaActiva.nombre}`;

  limpiarBorradorOrden();
  await cargarCuentaAbiertaMesa();
}

async function cargarCuentaAbiertaMesa() {
  const card = document.getElementById('cuenta-abierta-card');
  const detalleDiv = document.getElementById('cuenta-abierta-detalle');
  const badge = document.getElementById('cuenta-abierta-estado');

  if (!mesaActiva || !mesaActiva.orden_activa_id) {
    ordenActivaDetalle = null;
    card.classList.add('hidden');
    return;
  }

  const res = await fetch(`/api/pos/ordenes/${mesaActiva.orden_activa_id}`);
  if (!res.ok) {
    ordenActivaDetalle = null;
    card.classList.add('hidden');
    return;
  }
  const orden = await res.json();
  ordenActivaDetalle = orden;
  card.classList.remove('hidden');

  const estadoCocinaMap = {
    preparando: 'COCINA: EN TURNO',
    en_cola: 'COCINA: EN ESPERA',
    terminada: 'COCINA: ENTREGADA / SIN PENDIENTES'
  };
  badge.textContent = estadoCocinaMap[orden.estado_cocina] || `COCINA: ${(orden.estado_cocina || '').toUpperCase()}`;

  let html = '';
  orden.platos.forEach((p) => {
    const estPlato = p.terminado_cocina ? 'Entregado' : 'En cocina';
    html += `<div style="background:var(--surface-alt); border:1px solid var(--border); border-radius:6px; padding:8px 10px; margin-bottom:6px;">`;
    html += `<div style="display:flex; justify-content:space-between; font-size:0.84rem; font-weight:700; color:#93c5fd; margin-bottom:4px;">
      <span>Plato ${p.numero_plato} ${p.notas ? `(${p.notas})` : ''}</span>
      <span style="color:var(--text-muted);">${estPlato}</span>
    </div>`;
    p.items.forEach((i) => {
      html += `<div style="display:flex; justify-content:space-between; align-items:center; font-size:0.86rem; padding:2px 0;">
        <span>${i.cantidad}x ${i.producto} ($${i.subtotal_pesos.toFixed(2)})</span>
        <button class="btn btn-sm btn-secondary" style="padding:2px 6px; font-size:0.72rem;" onclick="eliminarItemDeCuentaAbierta(${orden.id}, ${i.id})">Quitar</button>
      </div>`;
    });
    html += `</div>`;
  });

  if (orden.bebidas.length > 0) {
    html += `<div style="background:var(--surface-alt); border:1px solid var(--border); border-radius:6px; padding:8px 10px; margin-bottom:6px;">`;
    html += `<div style="font-size:0.84rem; font-weight:700; color:#cbd5e1; margin-bottom:4px;">Refrescos y Bebidas (En mesa)</div>`;
    orden.bebidas.forEach((b) => {
      html += `<div style="display:flex; justify-content:space-between; align-items:center; font-size:0.86rem; padding:2px 0;">
        <span>${b.cantidad}x ${b.producto} ($${b.subtotal_pesos.toFixed(2)})</span>
        <button class="btn btn-sm btn-secondary" style="padding:2px 6px; font-size:0.72rem;" onclick="eliminarItemDeCuentaAbierta(${orden.id}, ${b.id})">Quitar</button>
      </div>`;
    });
    html += `</div>`;
  }

  html += `<div style="margin-top:10px; font-size:1.25rem; font-weight:700; color:#86efac;">Total de la Mesa: $${orden.total_pesos.toFixed(2)} MXN</div>`;
  detalleDiv.innerHTML = html;

  const inputRecibido = document.getElementById('input-monto-recibido');
  if (inputRecibido) {
    inputRecibido.value = orden.total_pesos.toFixed(2);
  }
  actualizarCalculoCambio();
}

async function eliminarItemDeCuentaAbierta(ordenId, itemId) {
  const res = await fetch(`/api/pos/ordenes/${ordenId}/items/${itemId}`, { method: 'DELETE' });
  if (res.ok) {
    showToast('Producto eliminado de la cuenta.', 'info');
    await loadMesasAndMenu();
    await cargarCuentaAbiertaMesa();
    await loadHistorialDiaAuxiliar();
    refreshCocinaBadgeSilent();
  }
}

async function cancelarCuentaMesaActual() {
  if (!mesaActiva || !mesaActiva.orden_activa_id) return;
  const res = await fetch(`/api/pos/ordenes/${mesaActiva.orden_activa_id}/cancelar`, { method: 'POST' });
  if (res.ok) {
    showToast(`Cuenta de ${mesaActiva.nombre} cancelada.`, 'info');
    ordenActivaDetalle = null;
    document.getElementById('cuenta-abierta-card').classList.add('hidden');
    await loadMesasAndMenu();
    await loadHistorialDiaAuxiliar();
    refreshCocinaBadgeSilent();
  }
}

function seleccionarMetodoPago(metodo) {
  metodoPagoSeleccionado = metodo;
  ['efectivo', 'tarjeta', 'transferencia'].forEach((m) => {
    const btn = document.getElementById(`btn-metodo-${m}`);
    if (!btn) return;
    if (m === metodo) {
      btn.classList.remove('btn-secondary');
    } else {
      btn.classList.add('btn-secondary');
    }
  });

  const bloqueEfectivo = document.getElementById('bloque-efectivo-cambio');
  if (bloqueEfectivo) {
    if (metodo === 'efectivo') {
      bloqueEfectivo.classList.remove('hidden');
      actualizarCalculoCambio();
    } else {
      bloqueEfectivo.classList.add('hidden');
    }
  }
}

function fijarMontoRecibido(valor) {
  const input = document.getElementById('input-monto-recibido');
  if (!input || !ordenActivaDetalle) return;
  if (valor === 'exacto') {
    input.value = ordenActivaDetalle.total_pesos.toFixed(2);
  } else {
    input.value = parseFloat(valor).toFixed(2);
  }
  actualizarCalculoCambio();
}

function actualizarCalculoCambio() {
  const textoCambio = document.getElementById('texto-cambio-entregar');
  const input = document.getElementById('input-monto-recibido');
  if (!textoCambio || !input || !ordenActivaDetalle) return;

  const total = ordenActivaDetalle.total_pesos || 0;
  const recibido = parseFloat(input.value || '0');
  const diff = recibido - total;

  if (diff < -0.005) {
    textoCambio.style.color = '#fca5a5';
    textoCambio.textContent = `Faltan $${Math.abs(diff).toFixed(2)}`;
  } else {
    textoCambio.style.color = '#86efac';
    textoCambio.textContent = `$${Math.max(0, diff).toFixed(2)} MXN`;
  }
}

async function confirmarCobroOrden() {
  if (!mesaActiva || !mesaActiva.orden_activa_id || !ordenActivaDetalle) return;

  const total = ordenActivaDetalle.total_pesos || 0;
  let montoRecibido = total;

  if (metodoPagoSeleccionado === 'efectivo') {
    const input = document.getElementById('input-monto-recibido');
    montoRecibido = parseFloat(input.value || '0');
    if (isNaN(montoRecibido) || montoRecibido < total) {
      showToast(`Monto recibido ($${(montoRecibido || 0).toFixed(2)}) menor al total ($${total.toFixed(2)}).`, 'error');
      return;
    }
  }

  const res = await fetch(`/api/pos/ordenes/${mesaActiva.orden_activa_id}/pagar`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      metodo_pago: metodoPagoSeleccionado,
      monto_recibido_pesos: montoRecibido
    })
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showToast(err.detail || 'No se pudo procesar el cobro.', 'error');
    return;
  }

  const data = await res.json();
  const msgCambio = data.metodo_pago === 'efectivo'
    ? ` | Cambio entregado: $${data.cambio_pesos.toFixed(2)}`
    : '';
  showToast(`Cuenta cobrada: $${data.total_pesos.toFixed(2)} (${data.metodo_pago.toUpperCase()})${msgCambio}`, 'success');

  ordenActivaDetalle = null;
  document.getElementById('cuenta-abierta-card').classList.add('hidden');
  await loadMesasAndMenu();
  await loadHistorialDiaAuxiliar();
  refreshCocinaBadgeSilent();
}

function renderMenuBotones() {
  const tacosGrid = document.getElementById('menu-tacos-grid');
  const bebidasGrid = document.getElementById('menu-bebidas-grid');
  if (!tacosGrid || !bebidasGrid) return;

  const platoActivo = borradorPlatos[platoActivoIndex] || { items: {} };
  const tacos = menuList.filter((p) => p.es_taco || p.categoria === 'tacos');
  const bebidas = menuList.filter((p) => !p.es_taco && p.categoria !== 'tacos');

  tacosGrid.innerHTML = tacos.map((p) => {
    const qty = platoActivo.items[p.id] || 0;
    const badge = qty > 0 ? `<span class="menu-qty-badge">${qty}</span>` : '';
    return `
      <button class="menu-btn" onclick="agregarTacoAPlatoActivo(${p.id})">
        ${badge}
        <span class="menu-btn-name">${p.nombre}</span>
        <span class="menu-btn-price">$${p.precio_pesos.toFixed(2)}</span>
      </button>
    `;
  }).join('');

  bebidasGrid.innerHTML = bebidas.map((p) => {
    const qty = borradorBebidas[p.id] || 0;
    const badge = qty > 0 ? `<span class="menu-qty-badge">${qty}</span>` : '';
    return `
      <button class="menu-btn" onclick="agregarBebidaAMesa(${p.id})">
        ${badge}
        <span class="menu-btn-name">${p.nombre}</span>
        <span class="menu-btn-price">$${p.precio_pesos.toFixed(2)}</span>
      </button>
    `;
  }).join('');
}

function renderPlatosTabs() {
  const container = document.getElementById('platos-tabs-container');
  if (!container) return;
  container.innerHTML = borradorPlatos.map((p, idx) => {
    const activeCls = idx === platoActivoIndex ? 'active' : '';
    const count = Object.values(p.items).reduce((a, b) => a + b, 0);
    return `<button class="plato-tab ${activeCls}" onclick="seleccionarPlatoTab(${idx})">Plato ${p.numero_plato}${count > 0 ? ` (${count})` : ''}</button>`;
  }).join('');

  const notaInput = document.getElementById('plato-notas-input');
  if (notaInput && borradorPlatos[platoActivoIndex]) {
    notaInput.value = borradorPlatos[platoActivoIndex].notas || '';
  }
}

function seleccionarPlatoTab(idx) {
  platoActivoIndex = idx;
  renderPlatosTabs();
  renderMenuBotones();
}

function agregarNuevoPlato() {
  const nuevoNum = borradorPlatos.length + 1;
  borradorPlatos.push({ numero_plato: nuevoNum, notas: '', items: {} });
  platoActivoIndex = borradorPlatos.length - 1;
  renderPlatosTabs();
  renderMenuBotones();
  renderBorradorResumen();
}

function agregarNotaRapidaPlato(nota) {
  const plato = borradorPlatos[platoActivoIndex];
  if (!plato) return;
  const actual = (plato.notas || '').trim();
  if (!actual) {
    plato.notas = nota;
  } else if (!actual.toLowerCase().includes(nota.toLowerCase())) {
    plato.notas = `${actual}, ${nota}`;
  }
  const notaInput = document.getElementById('plato-notas-input');
  if (notaInput) notaInput.value = plato.notas;
  renderBorradorResumen();
}

function actualizarNotaPlatoActivo(val) {
  if (borradorPlatos[platoActivoIndex]) {
    borradorPlatos[platoActivoIndex].notas = val;
    renderBorradorResumen();
  }
}

function agregarTacoAPlatoActivo(prodId) {
  const plato = borradorPlatos[platoActivoIndex];
  if (!plato) return;
  plato.items[prodId] = (plato.items[prodId] || 0) + 1;
  renderPlatosTabs();
  renderMenuBotones();
  renderBorradorResumen();
}

function cambiarCantidadPlatoItem(platoIdx, prodId, delta) {
  const plato = borradorPlatos[platoIdx];
  if (!plato) return;
  const nuevo = (plato.items[prodId] || 0) + delta;
  if (nuevo <= 0) {
    delete plato.items[prodId];
  } else {
    plato.items[prodId] = nuevo;
  }
  renderPlatosTabs();
  renderMenuBotones();
  renderBorradorResumen();
}

function agregarBebidaAMesa(prodId) {
  borradorBebidas[prodId] = (borradorBebidas[prodId] || 0) + 1;
  renderMenuBotones();
  renderBorradorResumen();
}

function cambiarCantidadBebida(prodId, delta) {
  const nuevo = (borradorBebidas[prodId] || 0) + delta;
  if (nuevo <= 0) {
    delete borradorBebidas[prodId];
  } else {
    borradorBebidas[prodId] = nuevo;
  }
  renderMenuBotones();
  renderBorradorResumen();
}

function limpiarBorradorOrden() {
  borradorPlatos = [{ numero_plato: 1, notas: '', items: {} }];
  platoActivoIndex = 0;
  borradorBebidas = {};
  renderPlatosTabs();
  renderMenuBotones();
  renderBorradorResumen();
}

function renderBorradorResumen() {
  const container = document.getElementById('borrador-resumen-container');
  if (!container) return;
  let totalPesos = 0;
  let totalTacos = 0;
  const conteoPorTaco = {};
  let html = '';

  borradorPlatos.forEach((p, pIdx) => {
    const prodIds = Object.keys(p.items);
    if (prodIds.length === 0) return;

    html += `<div style="background:var(--surface-alt); padding:10px; border-radius:6px; margin-bottom:8px; border-left:3px solid var(--primary);">`;
    html += `<div style="font-weight:700; color:#93c5fd; margin-bottom:4px;">Plato ${p.numero_plato} ${p.notas ? `<span style="font-weight:400; color:var(--text-muted);">(${p.notas})</span>` : ''}</div>`;

    prodIds.forEach((idStr) => {
      const prod = menuList.find((m) => m.id === parseInt(idStr));
      const cant = p.items[idStr];
      if (!prod) return;
      const sub = prod.precio_pesos * cant;
      totalPesos += sub;
      if (prod.es_taco) {
        totalTacos += cant;
        conteoPorTaco[prod.nombre] = (conteoPorTaco[prod.nombre] || 0) + cant;
      }
      html += `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px;">
          <span><strong>${cant}</strong> de ${prod.nombre} ($${sub.toFixed(2)})</span>
          <div>
            <button class="btn btn-sm btn-secondary" onclick="cambiarCantidadPlatoItem(${pIdx}, ${prod.id}, -1)">-</button>
            <button class="btn btn-sm btn-secondary" onclick="cambiarCantidadPlatoItem(${pIdx}, ${prod.id}, 1)">+</button>
          </div>
        </div>
      `;
    });
    html += `</div>`;
  });

  const bebIds = Object.keys(borradorBebidas);
  if (bebIds.length > 0) {
    html += `<div style="background:var(--surface-alt); padding:10px; border-radius:6px; margin-bottom:8px; border-left:3px solid #64748b;">`;
    html += `<div style="font-weight:700; color:#cbd5e1; margin-bottom:4px;">Refrescos / Bebidas (Solo Auxiliar)</div>`;
    bebIds.forEach((idStr) => {
      const prod = menuList.find((m) => m.id === parseInt(idStr));
      const cant = borradorBebidas[idStr];
      if (!prod) return;
      const sub = prod.precio_pesos * cant;
      totalPesos += sub;
      html += `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px;">
          <span><strong>${cant}</strong>x ${prod.nombre} ($${sub.toFixed(2)})</span>
          <div>
            <button class="btn btn-sm btn-secondary" onclick="cambiarCantidadBebida(${prod.id}, -1)">-</button>
            <button class="btn btn-sm btn-secondary" onclick="cambiarCantidadBebida(${prod.id}, 1)">+</button>
          </div>
        </div>
      `;
    });
    html += `</div>`;
  }

  if (!html) {
    container.innerHTML = `<div style="color:var(--text-muted); font-size:0.86rem;">Selecciona los tacos o bebidas para agregarlos a la cuenta de la mesa.</div>`;
    return;
  }

  const desgloseTexto = Object.entries(conteoPorTaco).map(([nombre, c]) => `${c} de ${nombre}`).join(' | ');
  html += `
    <div style="border-top:1px solid var(--border); padding-top:10px; margin-top:8px;">
      <div style="font-size:0.86rem; color:#cbd5e1; font-weight:600;">Tacos a enviar a cocina: ${totalTacos} (${desgloseTexto || 'Ninguno'})</div>
      <div style="font-size:1.08rem; font-weight:700; margin-top:4px;">Importe a agregar: $${totalPesos.toFixed(2)} MXN</div>
    </div>
  `;
  container.innerHTML = html;
}

async function enviarOrdenACocina() {
  if (!mesaActiva) {
    showToast('Primero selecciona una mesa.', 'error');
    return;
  }

  const platosPayload = borradorPlatos
    .map((p) => ({
      numero_plato: p.numero_plato,
      notas: p.notas,
      items: Object.entries(p.items).map(([prodId, cantidad]) => ({
        producto_id: parseInt(prodId),
        cantidad: cantidad,
        notas: ''
      }))
    }))
    .filter((p) => p.items.length > 0);

  const bebidasPayload = Object.entries(borradorBebidas).map(([prodId, cantidad]) => ({
    producto_id: parseInt(prodId),
    cantidad: cantidad,
    notas: ''
  }));

  if (platosPayload.length === 0 && bebidasPayload.length === 0) {
    showToast('Agrega al menos un taco o bebida antes de guardar en la mesa.', 'error');
    return;
  }

  const btn = document.getElementById('btn-enviar-orden');
  if (btn) btn.disabled = true;

  try {
    const res = await fetch('/api/pos/ordenes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mesa_id: mesaActiva.id,
        mesero: 'Auxiliar',
        platos: platosPayload,
        bebidas: bebidasPayload
      })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || 'Error al guardar el pedido.', 'error');
      return;
    }

    const data = await res.json();
    limpiarBorradorOrden();
    await loadMesasAndMenu();
    mesaActiva = mesasList.find((m) => m.id === mesaActiva.id);
    await cargarCuentaAbiertaMesa();
    await loadHistorialDiaAuxiliar();
    await refreshCocinaBadgeSilent();

    if (data.enviado_a_cocina) {
      showToast(`Pedido guardado en ${data.mesa} y tacos enviados a Cocina.`, 'success');
    } else {
      showToast(`Bebidas agregadas a la cuenta de ${data.mesa}.`, 'success');
    }
  } catch (e) {
    showToast('No se pudo conectar con el servidor.', 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadHistorialDiaAuxiliar() {
  const tbody = document.querySelector('#tabla-historial-auxiliar tbody');
  if (!tbody) return;

  try {
    const res = await fetch('/api/pos/ordenes-historial-dia');
    if (!res.ok) return;
    const lista = await res.json();
    if (!lista || lista.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" style="color:var(--text-muted);">Sin órdenes registradas hoy.</td></tr>`;
      return;
    }
    tbody.innerHTML = lista.map((o) => {
      const badgeCls = o.estado === 'pagada' ? 'badge-ok' : (o.estado === 'cancelada' ? 'badge-danger' : 'badge-info');
      const estadoTxt = o.estado.toUpperCase();
      return `
        <tr>
          <td>#${o.id}</td>
          <td>${o.hora}</td>
          <td><strong>${o.mesa}</strong></td>
          <td>${o.resumen_items || '-'}</td>
          <td>${o.estado === 'pagada' ? o.metodo_pago.toUpperCase() : '-'}</td>
          <td><strong>$${o.total_pesos.toFixed(2)}</strong></td>
          <td>${o.estado === 'pagada' ? `$${o.monto_recibido_pesos.toFixed(2)}` : '-'}</td>
          <td>${o.estado === 'pagada' ? `$${o.cambio_pesos.toFixed(2)}` : '-'}</td>
          <td><span class="badge ${badgeCls}">${estadoTxt}</span></td>
        </tr>
      `;
    }).join('');
  } catch (e) {}
}

async function loadColaCocina() {
  const res = await fetch('/api/pos/cocina/cola');
  if (!res.ok) return;
  const data = await res.json();

  const actualDiv = document.getElementById('kds-orden-actual-container');
  const esperaDiv = document.getElementById('kds-cola-espera-container');
  const contadorBadge = document.getElementById('kds-contador-espera');
  const navBadge = document.getElementById('nav-cocina-badge');

  contadorBadge.textContent = `${data.ordenes_en_espera.length} en espera`;
  if (navBadge) navBadge.textContent = data.total_ordenes_pendientes || 0;

  if (!data.orden_en_turno) {
    actualDiv.innerHTML = `
      <div class="card" style="text-align:center; padding:28px;">
        <h3 style="color:#86efac;">Sin pedidos de tacos pendientes en cocina</h3>
        <p style="color:var(--text-muted); margin-top:6px;">Los nuevos pedidos de tacos aparecerán aquí automáticamente.</p>
      </div>
    `;
  } else {
    const o = data.orden_en_turno;
    const platosHtml = o.platos.map((p) => `
      <div class="kds-plato-box">
        <div class="kds-plato-title">
          Plato ${p.numero_plato} ${p.notas ? `<span style="color:#e2e8f0; font-weight:600;">— (${p.notas})</span>` : ''}
        </div>
        <div class="kds-plato-items">${p.resumen_texto}</div>
      </div>
    `).join('');

    const chipsTacos = Object.entries(o.desglose_tacos).map(([tipo, cant]) => `
      <span class="kds-chip">${cant} de ${tipo}</span>
    `).join('');

    actualDiv.innerHTML = `
      <div class="kds-active-order">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
          <div>
            <span class="badge badge-ok" style="font-size:0.82rem; margin-right:8px;">ORDEN EN TURNO (#1)</span>
            <strong style="font-size:1.25rem;">${o.mesa} (Folio #${o.orden_id})</strong>
          </div>
          <span style="color:var(--text-muted); font-weight:600;">Hora: ${o.hora}</span>
        </div>

        <div>${platosHtml}</div>

        <div class="kds-summary-bar">
          <div style="font-size:1.05rem; font-weight:700; color:#93c5fd; margin-bottom:6px;">
            TOTAL DE TACOS EN ESTA ORDEN: ${o.total_tacos} piezas
          </div>
          <div>${chipsTacos || '<span style="color:var(--text-muted);">0 tacos</span>'}</div>
        </div>

        <button class="btn btn-success btn-block" onclick="terminarOrdenCocina(${o.orden_id})">
          MARCAR ORDEN TERMINADA Y AVANZAR SIGUIENTE
        </button>
      </div>
    `;
  }

  if (data.ordenes_en_espera.length === 0) {
    esperaDiv.innerHTML = `<div style="color:var(--text-muted); font-size:0.88rem;">No hay más órdenes en lista de espera.</div>`;
  } else {
    esperaDiv.innerHTML = data.ordenes_en_espera.map((ord) => {
      const chips = Object.entries(ord.desglose_tacos).map(([tipo, cant]) => `
        <span class="kds-chip" style="font-size:0.85rem;">${cant} de ${tipo}</span>
      `).join('');

      return `
        <div class="kds-queue-item">
          <div>
            <div style="font-weight:700; font-size:0.98rem;">
              Turno #${ord.posicion_cola} | ${ord.mesa} (Folio #${ord.orden_id})
              <span style="font-size:0.78rem; color:var(--text-muted); margin-left:6px;">(${ord.cantidad_platos} platos — el desglose por plato se muestra al entrar en turno)</span>
            </div>
            <div style="margin-top:6px;">
              ${chips || '<span style="color:var(--text-muted);">Sin tacos</span>'}
            </div>
          </div>
          <div style="text-align:right;">
            <div style="font-size:1.15rem; font-weight:700; color:#93c5fd;">Total: ${ord.total_tacos} tacos</div>
            <div style="font-size:0.78rem; color:var(--text-muted);">Hora: ${ord.hora}</div>
          </div>
        </div>
      `;
    }).join('');
  }
}

async function terminarOrdenCocina(ordenId) {
  const res = await fetch(`/api/pos/cocina/${ordenId}/terminar`, { method: 'POST' });
  if (res.ok) {
    showToast(`Orden #${ordenId} marcada como terminada en cocina.`, 'success');
    await loadColaCocina();
  }
}

function cambiarFactorSimulacion(factor) {
  factorSimulacionActual = factor;
  const mapIds = {
    '0.85': 'btn-sim-085',
    '1': 'btn-sim-100',
    '1.15': 'btn-sim-115',
    '1.3': 'btn-sim-130'
  };
  Object.entries(mapIds).forEach(([val, id]) => {
    const btn = document.getElementById(id);
    if (!btn) return;
    if (parseFloat(val) === factor) {
      btn.classList.remove('btn-secondary');
    } else {
      btn.classList.add('btn-secondary');
    }
  });
  loadAdminAnalytics();
}

async function guardarCorteCajaActual() {
  const fondo = parseFloat(document.getElementById('input-fondo-caja').value || '1000');
  const contadoStr = document.getElementById('input-efectivo-contado').value;
  if (contadoStr === '') {
    showToast('Ingresa el efectivo físico contado antes de guardar el corte.', 'error');
    return;
  }
  const res = await fetch('/api/pos/admin/guardar-corte', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      fondo_inicial_pesos: fondo,
      efectivo_contado_pesos: parseFloat(contadoStr)
    })
  });
  if (res.ok) {
    const data = await res.json();
    showToast(`Corte #${data.corte_id} guardado (${data.estado_cuadre.toUpperCase()}).`, 'success');
    loadAdminAnalytics();
  }
}

async function loadAdminAnalytics() {
  const fondo = parseFloat(document.getElementById('input-fondo-caja').value || '1000');
  const contadoStr = document.getElementById('input-efectivo-contado').value;
  let url = `/api/pos/admin/analytics?fondo_inicial_pesos=${fondo}&factor_simulacion=${factorSimulacionActual}`;
  if (contadoStr !== '') {
    url += `&efectivo_contado_pesos=${parseFloat(contadoStr)}`;
  }

  const res = await fetch(url);
  if (!res.ok) return;
  const data = await res.json();

  document.getElementById('stat-ventas-hoy').textContent = `$${data.ventas_totales_pesos.toFixed(2)}`;
  const desgloseMetodos = document.getElementById('stat-desglose-metodos');
  if (desgloseMetodos) {
    const ef = (data.ventas_efectivo_pesos || 0).toFixed(2);
    const tj = (data.ventas_tarjeta_pesos || 0).toFixed(2);
    const tr = (data.ventas_transferencia_pesos || 0).toFixed(2);
    desgloseMetodos.textContent = `Efectivo: $${ef} | Tarjeta: $${tj} | Transf: $${tr}`;
  }
  document.getElementById('stat-gastos-hoy').textContent = `$${data.gastos_pesos.toFixed(2)}`;
  document.getElementById('stat-efectivo-esperado').textContent = `$${data.reconciliacion.saldo_teorico_pesos.toFixed(2)}`;
  document.getElementById('stat-diferencia-caja').textContent = `$${data.reconciliacion.diferencia_pesos.toFixed(2)}`;

  const cuadreDiv = document.getElementById('stat-cuadre-mensaje');
  if (data.reconciliacion.estado_cuadre === 'exacto') {
    cuadreDiv.innerHTML = `<span class="badge badge-ok">Caja Cuadrada Exacta</span>`;
  } else if (data.reconciliacion.estado_cuadre === 'faltante') {
    cuadreDiv.innerHTML = `<span class="badge badge-danger">Faltante de Caja: -$${Math.abs(data.reconciliacion.diferencia_pesos).toFixed(2)} MXN</span>`;
  } else {
    cuadreDiv.innerHTML = `<span class="badge badge-ok">Sobrante en Caja: +$${data.reconciliacion.diferencia_pesos.toFixed(2)} MXN</span>`;
  }

  const cusumMsg = `Diferencia acumulada en turnos recientes: $${data.cusum.cusum_score_pesos.toFixed(2)} / Límite de alerta: $${data.cusum.threshold_pesos.toFixed(2)} MXN`;
  document.getElementById('stat-cusum-mensaje').textContent = cusumMsg;

  const iaCusumDiv = document.getElementById('ia-cusum-detalle');
  if (iaCusumDiv) {
    const alertaBadge = data.cusum.alarm_triggered
      ? `<span class="badge badge-danger">Alerta de Fuga Sistemática Detectada</span>`
      : `<span class="badge badge-ok">Sin Fuga Sistemática</span>`;
    iaCusumDiv.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; background:var(--surface-alt); padding:10px; border-radius:6px; border:1px solid var(--border);">
        <span>Acumulado CUSUM: <strong>$${data.cusum.cusum_score_pesos.toFixed(2)} MXN</strong> (Umbral: $${data.cusum.threshold_pesos.toFixed(2)})</span>
        ${alertaBadge}
      </div>
    `;
  }

  if (data.resumen_pronostico) {
    const r = data.resumen_pronostico;
    const elV7 = document.getElementById('sim-venta-7d');
    const elVF = document.getElementById('sim-venta-finde');
    const elC7 = document.getElementById('sim-carne-7d');
    const elCab = document.getElementById('sim-cabezas-7d');
    const elT7 = document.getElementById('sim-tortilla-7d');
    if (elV7) elV7.textContent = `$${r.venta_7d_pesos.toFixed(2)}`;
    if (elVF) elVF.textContent = `$${r.venta_finde_pesos.toFixed(2)}`;
    if (elC7) elC7.textContent = `${r.carne_7d_kg} kg`;
    if (elCab) elCab.textContent = `Equivalente a ${r.cabezas_7d_piezas} cabezas de res`;
    if (elT7) elT7.textContent = `${r.tortilla_7d_kg} kg`;
  }

  const tbodyGastos = document.querySelector('#tabla-ultimos-gastos tbody');
  if (tbodyGastos) {
    tbodyGastos.innerHTML = data.ultimos_gastos_whatsapp.map((g) => `
      <tr>
        <td>${g.concepto}</td>
        <td>${g.tipo}</td>
        <td><strong>$${g.importe_pesos.toFixed(2)}</strong></td>
      </tr>
    `).join('');
  }

  const tbodyHistorialAdmin = document.querySelector('#tabla-historial-admin tbody');
  if (tbodyHistorialAdmin) {
    const hist = data.historial_ordenes_hoy || [];
    if (hist.length === 0) {
      tbodyHistorialAdmin.innerHTML = `<tr><td colspan="10" style="color:var(--text-muted);">Sin órdenes registradas el día de hoy.</td></tr>`;
    } else {
      tbodyHistorialAdmin.innerHTML = hist.map((o) => {
        const badgeCls = o.estado === 'pagada' ? 'badge-ok' : (o.estado === 'cancelada' ? 'badge-danger' : 'badge-info');
        return `
          <tr>
            <td>#${o.id}</td>
            <td>${o.hora}</td>
            <td><strong>${o.mesa}</strong></td>
            <td>${o.mesero}</td>
            <td>${o.resumen_items || '-'}</td>
            <td>${o.estado === 'pagada' ? o.metodo_pago.toUpperCase() : '-'}</td>
            <td><strong>$${o.total_pesos.toFixed(2)}</strong></td>
            <td>${o.estado === 'pagada' ? `$${o.monto_recibido_pesos.toFixed(2)}` : '-'}</td>
            <td>${o.estado === 'pagada' ? `$${o.cambio_pesos.toFixed(2)}` : '-'}</td>
            <td><span class="badge ${badgeCls}">${o.estado.toUpperCase()}</span></td>
          </tr>
        `;
      }).join('');
    }
  }

  const tbodyPred = document.querySelector('#tabla-pronostico-ml tbody');
  if (tbodyPred) {
    tbodyPred.innerHTML = data.pronostico_7_dias.map((p) => {
      const cabezas = p.cabezas_res_sugeridas !== undefined ? p.cabezas_res_sugeridas : (p.kilos_carne_sugeridos / 4.5).toFixed(1);
      return `
        <tr>
          <td>${p.fecha}</td>
          <td><strong>${p.dia_semana}</strong> ${p.es_fin_de_semana ? '(Fin de semana)' : ''}</td>
          <td>$${p.escenario_pesimista_p10.toFixed(2)}</td>
          <td><strong style="color:#86efac;">$${p.pronostico_pesos_p50.toFixed(2)}</strong></td>
          <td>$${p.escenario_optimista_p90.toFixed(2)}</td>
          <td>${p.tacos_estimados} pzs</td>
          <td><strong>${p.kilos_carne_sugeridos} kg</strong></td>
          <td>${cabezas} pzs</td>
          <td>${p.kilos_tortillas_sugeridos} kg</td>
        </tr>
      `;
    }).join('');
  }

  const tbodyCortes = document.querySelector('#tabla-historial-cortes tbody');
  if (tbodyCortes) {
    const cortes = data.historial_cortes || [];
    if (cortes.length === 0) {
      tbodyCortes.innerHTML = `<tr><td colspan="5" style="color:var(--text-muted);">Aún no hay cortes guardados. Usa "Guardar Corte del Turno" en la pestaña de Caja.</td></tr>`;
    } else {
      tbodyCortes.innerHTML = cortes.map((c) => {
        const cls = c.estado === 'exacto' ? 'badge-ok' : (c.estado === 'faltante' ? 'badge-danger' : 'badge-info');
        return `
          <tr>
            <td>${c.fecha}</td>
            <td>$${c.saldo_teorico_pesos.toFixed(2)}</td>
            <td>$${c.saldo_real_pesos.toFixed(2)}</td>
            <td><strong>$${c.diferencia_pesos.toFixed(2)}</strong></td>
            <td><span class="badge ${cls}">${c.estado.toUpperCase()}</span></td>
          </tr>
        `;
      }).join('');
    }
  }

  const tbodyMemoria = document.querySelector('#tabla-memoria-aprendida tbody');
  if (tbodyMemoria) {
    const mems = data.memoria_aprendida || [];
    if (mems.length === 0) {
      tbodyMemoria.innerHTML = `<tr><td colspan="4" style="color:var(--text-muted);">Sin conceptos personalizados aún. Se aprenden automáticamente al clasificar gastos por texto.</td></tr>`;
    } else {
      tbodyMemoria.innerHTML = mems.map((m) => `
        <tr>
          <td><strong>${m.palabra_clave}</strong></td>
          <td>${m.tipo_asignado}</td>
          <td>${m.proveedor || '-'}</td>
          <td>${m.frecuencia_uso}</td>
        </tr>
      `).join('');
    }
  }

  const tbodyPlatillos = document.querySelector('#tabla-reporte-platillos tbody');
  if (tbodyPlatillos) {
    if (!data.productos_vendidos_hoy || data.productos_vendidos_hoy.length === 0) {
      tbodyPlatillos.innerHTML = `<tr><td colspan="4" style="color:var(--text-muted);">Sin ventas cobradas hoy todavía.</td></tr>`;
    } else {
      tbodyPlatillos.innerHTML = data.productos_vendidos_hoy.map((prod) => `
        <tr>
          <td><strong>${prod.producto}</strong></td>
          <td>${prod.categoria}</td>
          <td>${prod.unidades} pzs</td>
          <td><strong>$${prod.total_pesos.toFixed(2)} MXN</strong></td>
        </tr>
      `).join('');
    }
  }
}

async function enviarGastoRapido() {
  const input = document.getElementById('input-gasto-rapido');
  const respDiv = document.getElementById('respuesta-asistente-texto');
  const msg = input.value.trim();
  if (!msg) return;

  const res = await fetch('/webhook/simulate-message', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone: 'admin_panel', message: msg })
  });
  if (res.ok) {
    const data = await res.json();
    input.value = '';
    if (respDiv && data.reply) {
      respDiv.textContent = data.reply;
    }
    showToast(data.reply || 'Movimiento registrado correctamente.', 'success');
    loadAdminAnalytics();
    loadInventarioAdmin();
  }
}

async function loadInventarioAdmin() {
  const res = await fetch('/api/pos/inventario');
  if (!res.ok) return;
  inventarioList = await res.json();

  const tbody = document.querySelector('#tabla-inventario tbody');
  tbody.innerHTML = inventarioList.map((i) => {
    const badge = i.bajo_stock
      ? `<span class="badge badge-danger">Bajo (Mín: ${i.stock_minimo})</span>`
      : `<span class="badge badge-ok">Normal</span>`;
    const step = i.unidad === 'pieza' ? 1 : 5;
    return `
      <tr>
        <td><strong>${i.nombre}</strong></td>
        <td>${i.unidad.toUpperCase()}</td>
        <td style="font-size:1rem; font-weight:700;">${i.stock_actual} ${i.unidad}</td>
        <td>${badge}</td>
        <td style="display:flex; gap:6px;">
          <button class="btn btn-sm btn-success" onclick="ajustarInsumo(${i.id}, 'entrada', ${step})">+${step} Entrada</button>
          <button class="btn btn-sm btn-danger" onclick="ajustarInsumo(${i.id}, 'merma', 1)">-1 Salida</button>
        </td>
      </tr>
    `;
  }).join('');

  const selectInsumo = document.getElementById('menu-nuevo-insumo');
  if (selectInsumo) {
    selectInsumo.innerHTML = `<option value="">Sin descontar insumo específico</option>` +
      inventarioList.map((i) => `<option value="${i.id}">${i.nombre} (${i.unidad})</option>`).join('');
  }
}

async function ajustarInsumo(insumoId, tipo, cantidad) {
  const res = await fetch(`/api/pos/inventario/${insumoId}/movimiento`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tipo, cantidad })
  });
  if (res.ok) {
    const data = await res.json();
    showToast(`${data.insumo}: ${data.stock_actual} ${data.unidad}`, 'success');
    loadInventarioAdmin();
  }
}

async function crearInsumoAdmin() {
  const nombre = document.getElementById('inv-nombre').value.trim();
  const categoria_insumo = document.getElementById('inv-categoria').value;
  const unidad = document.getElementById('inv-unidad').value;
  const stock_actual = parseFloat(document.getElementById('inv-stock').value || '0');
  const stock_minimo = parseFloat(document.getElementById('inv-minimo').value || '1');

  if (!nombre) return;
  const res = await fetch('/api/pos/inventario', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      nombre,
      categoria_insumo,
      unidad,
      stock_actual,
      stock_minimo,
      costo_unitario_pesos: 0
    })
  });
  if (res.ok) {
    document.getElementById('inv-nombre').value = '';
    showToast(`Insumo "${nombre}" guardado.`, 'success');
    loadInventarioAdmin();
  }
}

async function loadMenuAndMesasAdmin() {
  await loadMesasAndMenu();

  const tbody = document.querySelector('#tabla-menu-admin tbody');
  tbody.innerHTML = menuList.map((p) => `
    <tr>
      <td><strong>${p.nombre}</strong></td>
      <td>${p.categoria}</td>
      <td>
        <input type="number" class="input" style="width:90px; padding:4px 8px; display:inline-block;" value="${p.precio_pesos}" id="precio-prod-${p.id}" />
      </td>
      <td style="display:flex; gap:6px;">
        <button class="btn btn-sm" onclick="guardarPrecioInline(${p.id}, '${p.nombre.replace(/'/g, "\\'")}', '${p.categoria}', ${p.es_taco})">Guardar $</button>
        <button class="btn btn-sm btn-danger" onclick="borrarProductoAdmin(${p.id})">Eliminar</button>
      </td>
    </tr>
  `).join('');

  const mesasAdminDiv = document.getElementById('lista-mesas-admin');
  mesasAdminDiv.innerHTML = mesasList.map((m) => `
    <div class="mesa-card libre">
      <div class="mesa-name">${m.nombre}</div>
      <button class="btn btn-sm btn-danger" style="margin-top:6px;" onclick="borrarMesaAdmin(${m.id})">Eliminar</button>
    </div>
  `).join('');
}

async function guardarPrecioInline(id, nombre, categoria, esTaco) {
  const input = document.getElementById(`precio-prod-${id}`);
  if (!input) return;
  const precioNum = parseFloat(input.value || '0');
  if (isNaN(precioNum) || precioNum <= 0) {
    showToast('Ingresa un precio válido.', 'error');
    return;
  }

  const res = await fetch(`/api/pos/menu/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      nombre,
      categoria,
      precio_pesos: precioNum,
      costo_pesos: 0,
      es_taco: esTaco
    })
  });
  if (res.ok) {
    showToast(`Precio de ${nombre} actualizado a $${precioNum.toFixed(2)}`, 'success');
    loadMenuAndMesasAdmin();
  }
}

async function crearProductoAdmin() {
  const nombre = document.getElementById('menu-nuevo-nombre').value.trim();
  const precio = parseFloat(document.getElementById('menu-nuevo-precio').value || '0');
  const categoria = document.getElementById('menu-nuevo-cat').value;
  const insumoIdStr = document.getElementById('menu-nuevo-insumo').value;

  if (!nombre || precio <= 0) {
    showToast('Ingresa nombre y precio del producto.', 'error');
    return;
  }

  const res = await fetch('/api/pos/menu', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      nombre,
      categoria,
      precio_pesos: precio,
      costo_pesos: 0,
      es_taco: categoria === 'tacos',
      insumo_id: insumoIdStr ? parseInt(insumoIdStr) : null,
      factor_consumo_insumo: categoria === 'tacos' ? 0.05 : 1.0
    })
  });

  if (res.ok) {
    document.getElementById('menu-nuevo-nombre').value = '';
    document.getElementById('menu-nuevo-precio').value = '';
    showToast(`Producto "${nombre}" agregado al menú.`, 'success');
    loadMenuAndMesasAdmin();
  }
}

async function borrarProductoAdmin(id) {
  await fetch(`/api/pos/menu/${id}`, { method: 'DELETE' });
  showToast('Producto eliminado del menú.', 'info');
  loadMenuAndMesasAdmin();
}

async function crearMesaAdmin() {
  const nombre = document.getElementById('mesa-nueva-nombre').value.trim();
  if (!nombre) return;
  const res = await fetch('/api/pos/mesas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nombre, orden: mesasList.length + 1 })
  });
  if (res.ok) {
    document.getElementById('mesa-nueva-nombre').value = '';
    showToast(`Mesa "${nombre}" agregada.`, 'success');
    loadMenuAndMesasAdmin();
  }
}

async function borrarMesaAdmin(id) {
  await fetch(`/api/pos/mesas/${id}`, { method: 'DELETE' });
  showToast('Mesa desactivada.', 'info');
  loadMenuAndMesasAdmin();
}

async function subirHistoricoDidan() {
  const fileInput = document.getElementById('import-file-input');
  const fechaInput = document.getElementById('import-fecha-input').value;
  const msgDiv = document.getElementById('import-resultado-msg');

  if (!fileInput.files || fileInput.files.length === 0) {
    showToast('Selecciona al menos un archivo .html, .json o .csv', 'error');
    return;
  }

  let resultados = [];
  for (const f of fileInput.files) {
    const formData = new FormData();
    formData.append('file', f);
    if (fechaInput) formData.append('fecha_reporte', fechaInput);

    const res = await fetch('/api/pos/admin/import-history', {
      method: 'POST',
      body: formData
    });
    if (res.ok) {
      const data = await res.json();
      resultados.push(`Importado: ${data.archivo} — $${data.total_ventas_pesos.toFixed(2)} MXN (${data.unidades_totales} unidades)`);
    } else {
      const err = await res.json();
      resultados.push(`Error en ${f.name}: ${err.detail}`);
    }
  }

  msgDiv.innerHTML = resultados.map((r) => `<div>${r}</div>`).join('');
  showToast('Importación de historial completada.', 'success');
  loadAdminAnalytics();
}

function toggleMostrarPinsUsuarios() {
  mostrarPinsEnTabla = !mostrarPinsEnTabla;
  const btn = document.getElementById('btn-toggle-pins');
  if (btn) {
    btn.textContent = mostrarPinsEnTabla ? 'Ocultar PINs' : 'Mostrar PINs';
  }
  loadUsuariosAdmin();
}

async function loadUsuariosAdmin() {
  const res = await fetch('/api/pos/usuarios');
  if (!res.ok) return;
  const usuarios = await res.json();
  const tbody = document.querySelector('#tabla-usuarios-admin tbody');
  if (!tbody) return;

  tbody.innerHTML = usuarios.map((u) => `
    <tr>
      <td><strong>${u.nombre}</strong></td>
      <td><span class="badge badge-ok">${u.rol.toUpperCase()}</span></td>
      <td><code>${mostrarPinsEnTabla ? u.pin : '••••'}</code></td>
      <td>
        <button class="btn btn-sm btn-danger" onclick="borrarUsuarioAdmin(${u.id})">Eliminar</button>
      </td>
    </tr>
  `).join('');
}

async function crearUsuarioAdmin() {
  const nombre = document.getElementById('user-nuevo-nombre').value.trim();
  const rol = document.getElementById('user-nuevo-rol').value;
  const pin = document.getElementById('user-nuevo-pin').value.trim();
  if (!nombre || !pin) {
    showToast('Ingresa nombre y PIN.', 'error');
    return;
  }

  const res = await fetch('/api/pos/usuarios', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ nombre, rol, pin })
  });
  if (res.ok) {
    document.getElementById('user-nuevo-nombre').value = '';
    document.getElementById('user-nuevo-pin').value = '';
    showToast(`Usuario "${nombre}" creado.`, 'success');
    loadUsuariosAdmin();
  }
}

async function borrarUsuarioAdmin(id) {
  await fetch(`/api/pos/usuarios/${id}`, { method: 'DELETE' });
  showToast('Usuario eliminado.', 'info');
  loadUsuariosAdmin();
}
