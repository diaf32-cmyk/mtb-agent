export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  try {
    const response = await fetch(
      'https://api.github.com/repos/diaf32-cmyk/mtb-agent/actions/workflows/garmin_sync.yml/dispatches',
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${process.env.GITHUB_TOKEN}`,
          'Accept': 'application/vnd.github.v3+json',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ ref: 'main' })
      }
    );
    if (response.status === 204) {
      return res.status(200).json({ ok: true, message: 'Sync iniciado' });
    } else {
      const data = await response.json();
      return res.status(response.status).json({ error: data.message });
    }
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
}
