// Simple dashboard script to interact with the Eazymode/Ecomrocket API.
// This script provides a minimal proof‑of‑concept for the Owner dashboard.

document.addEventListener('DOMContentLoaded', () => {
  const tenantInput = document.getElementById('tenantId');
  const loadBtn = document.getElementById('loadBrandsBtn');
  const createBtn = document.getElementById('createBrandBtn');
  const output = document.getElementById('output');

  loadBtn.addEventListener('click', () => {
    const tenant = tenantInput.value.trim();
    if (!tenant) {
      alert('Enter a tenant ID first');
      return;
    }
    loadBrands(tenant);
  });

  createBtn.addEventListener('click', async () => {
    const tenant = tenantInput.value.trim();
    if (!tenant) {
      alert('Enter a tenant ID first');
      return;
    }
    const name = prompt('Enter a new brand name:');
    if (!name) return;
    try {
      const resp = await fetch(`/tenant/${tenant}/brand`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
      });
      if (!resp.ok) {
        const msg = await resp.text();
        throw new Error(msg);
      }
      await loadBrands(tenant);
    } catch (err) {
      alert('Error creating brand: ' + err.message);
    }
  });

  async function loadBrands(tenantId) {
    output.innerHTML = '<em>Loading brands...</em>';
    try {
      const resp = await fetch(`/tenant/${tenantId}/brands`);
      if (!resp.ok) throw new Error(await resp.text());
      const brands = await resp.json();
      if (brands.length === 0) {
        output.innerHTML = '<p>No brands found. Create one using the button above.</p>';
        return;
      }
      output.innerHTML = '';
      for (const brand of brands) {
        const div = document.createElement('div');
        div.className = 'brand';
        div.innerHTML = `<h2>${brand.name}</h2><p><strong>Brand ID:</strong> ${brand.id}</p>`;
        const details = document.createElement('div');
        div.appendChild(details);
        output.appendChild(div);
        // Load phaseglass and schedule for each brand
        loadBrandDetails(tenantId, brand.id, details);
      }
    } catch (err) {
      output.innerHTML = '<p>Error loading brands: ' + err.message + '</p>';
    }
  }

  async function loadBrandDetails(tenantId, brandId, container) {
    container.innerHTML = '<em>Loading details...</em>';
    try {
      const [glassResp, schedResp] = await Promise.all([
        fetch(`/tenant/${tenantId}/brand/${brandId}/phaseglass`),
        fetch(`/tenant/${tenantId}/brand/${brandId}/schedule`),
      ]);
      if (!glassResp.ok) throw new Error(await glassResp.text());
      if (!schedResp.ok) throw new Error(await schedResp.text());
      const glass = await glassResp.json();
      const sched = await schedResp.json();
      const pre = document.createElement('pre');
      pre.textContent = JSON.stringify({ phaseglass: glass, schedule: sched }, null, 2);
      container.innerHTML = '';
      container.appendChild(pre);
    } catch (err) {
      container.innerHTML = '<p>Error loading details: ' + err.message + '</p>';
    }
  }
});