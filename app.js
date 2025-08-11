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
    // Call the enhanced brand loader
    if (typeof loadBrandsEnhanced === 'function') {
      loadBrandsEnhanced(tenant);
    } else {
      loadBrands(tenant);
    }
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
      if (typeof loadBrandsEnhanced === 'function') {
        await loadBrandsEnhanced(tenant);
      } else {
        await loadBrands(tenant);
      }
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

    // === Extended dashboard functions and handlers ===
    // Override default click handlers with enhanced ones that render phases and tasks
    loadBtn.addEventListener('click', () => {
      const tenant = tenantInput.value.trim();
      if (!tenant) {
        alert('Enter a tenant ID first');
        return;
      }
      loadBrandsEnhanced(tenant);
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
        if (!resp.ok) throw new Error(await resp.text());
        await loadBrandsEnhanced(tenant);
      } catch (err) {
        alert('Error creating brand: ' + err.message);
      }
    });

    /**
     * Enhanced brand loader: fetches brands and calls renderBrandEnhanced.
     */
    async function loadBrandsEnhanced(tenantId) {
      output.innerHTML = '<em>Loading brands...</em>';
      try {
        const resp = await fetch(`/tenant/${tenantId}/brands`);
        if (!resp.ok) throw new Error(await resp.text());
        const brands = await resp.json();
        output.innerHTML = '';
        if (!Array.isArray(brands) || brands.length === 0) {
          output.textContent = 'No brands found. Create one using the button above.';
          return;
        }
        brands.forEach(b => renderBrandEnhanced(tenantId, b));
      } catch (err) {
        output.textContent = 'Error loading brands: ' + err.message;
      }
    }

    /**
     * Render a single brand with Add Phase button and details container.
     * @param {string} tenantId
     * @param {{id: string, name: string}} brand
     */
    function renderBrandEnhanced(tenantId, brand) {
      const brandDiv = document.createElement('div');
      brandDiv.className = 'brand';
      const header = document.createElement('h2');
      header.textContent = brand.name;
      brandDiv.appendChild(header);
      const idSpan = document.createElement('div');
      idSpan.style.fontSize = '0.8rem';
      idSpan.style.color = '#555';
      idSpan.textContent = `Brand ID: ${brand.id}`;
      brandDiv.appendChild(idSpan);
      const addPhaseBtn = document.createElement('button');
      addPhaseBtn.textContent = 'Add Phase';
      addPhaseBtn.onclick = async () => {
        const name = prompt('Phase name:');
        if (!name) return;
        const key = prompt('Phase key (e.g. company_setup, supply_chain):');
        if (!key) return;
        const orderStr = prompt('Phase order (1, 2, 3...)');
        const order = parseInt(orderStr, 10) || 0;
        try {
          const resp = await fetch(`/tenant/${tenantId}/brand/${brand.id}/phase`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, key, order })
          });
          if (!resp.ok) throw new Error(await resp.text());
          await loadBrandsEnhanced(tenantId);
        } catch (err) {
          alert('Error creating phase: ' + err.message);
        }
      };
      brandDiv.appendChild(addPhaseBtn);
      const details = document.createElement('div');
      brandDiv.appendChild(details);
      output.appendChild(brandDiv);
      loadBrandDetailsEnhanced(tenantId, brand.id, details);
    }

    /**
     * Enhanced brand details loader: shows schedule, phases, tasks and Add Task buttons.
     * @param {string} tenantId
     * @param {string} brandId
     * @param {HTMLElement} container
     */
    async function loadBrandDetailsEnhanced(tenantId, brandId, container) {
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
        container.innerHTML = '';
        // Schedule summary
        const schedDiv = document.createElement('div');
        schedDiv.style.marginBottom = '0.5rem';
        const eta = sched.eta || 'n/a';
        const band = sched.band || '';
        const crit = Array.isArray(sched.critical) ? sched.critical.join(', ') : '';
        schedDiv.textContent = `Launch ETA: ${eta}${band ? ' ± ' + band : ''} | Critical path: ${crit}`;
        container.appendChild(schedDiv);
        if (Array.isArray(glass.phases)) {
          glass.phases.forEach(phase => {
            const phaseDiv = document.createElement('div');
            phaseDiv.className = 'phase';
            const phaseHeader = document.createElement('div');
            phaseHeader.innerHTML = `<strong>${phase.phase_name}</strong>`;
            phaseDiv.appendChild(phaseHeader);
            const barContainer = document.createElement('div');
            barContainer.className = 'phase-progress';
            const bar = document.createElement('div');
            bar.className = 'phase-progress-bar';
            const completion = Math.round((phase.completion || 0) * 100);
            bar.style.width = `${completion}%`;
            barContainer.appendChild(bar);
            phaseDiv.appendChild(barContainer);
            const status = document.createElement('div');
            status.style.fontSize = '0.8rem';
            status.style.color = '#666';
            status.textContent = `${completion}% complete`;
            phaseDiv.appendChild(status);
            const ul = document.createElement('ul');
            ul.className = 'task-list';
            if (Array.isArray(phase.tasks) && phase.tasks.length) {
              phase.tasks.forEach(task => {
                const li = document.createElement('li');
                li.textContent = `${task.task_name || task.title} - ${task.done ? 'Done' : 'Pending'}`;
                ul.appendChild(li);
              });
            } else {
              const li = document.createElement('li');
              li.textContent = 'No tasks yet';
              ul.appendChild(li);
            }
            phaseDiv.appendChild(ul);
            // Add Task button
            const addTaskBtn = document.createElement('button');
            addTaskBtn.textContent = 'Add Task';
            addTaskBtn.style.marginBottom = '0.5rem';
            addTaskBtn.onclick = async () => {
              const name = prompt('Task name:');
              if (!name) return;
              const durationStr = prompt('Duration in days:');
              const duration = parseInt(durationStr, 10) || 1;
              const weightStr = prompt('Task weight (0-1, optional):');
              const weight = weightStr ? parseFloat(weightStr) : undefined;
              const depsStr = prompt('Depends on (comma separated task IDs, optional):');
              let depends_on = [];
              if (depsStr) depends_on = depsStr.split(',').map(s => s.trim()).filter(Boolean);
              try {
                const body = { name, duration_days: duration };
                if (typeof weight !== 'undefined' && !Number.isNaN(weight)) body.weight = weight;
                if (depends_on.length > 0) body.depends_on = depends_on;
                const resp = await fetch(`/tenant/${tenantId}/brand/${brandId}/phase/${phase.phase_id}/task`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(body)
                });
                if (!resp.ok) throw new Error(await resp.text());
                await loadBrandDetailsEnhanced(tenantId, brandId, container);
              } catch (err) {
                alert('Error creating task: ' + err.message);
              }
            };
            phaseDiv.appendChild(addTaskBtn);
            container.appendChild(phaseDiv);
          });
        }
      } catch (err) {
        container.textContent = 'Error loading details: ' + err.message;
      }
    }
});