import { useState, useEffect } from 'react';
import { FileText, Download, Trash2 } from 'lucide-react';
import { fetchReports, deleteReport } from '../api/client';

export const Reports = () => {
  const [reports, setReports] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const loadReports = async () => {
    try {
      const data = await fetchReports();
      setReports(data.reports || []);
    } catch (error) {
      console.error("Failed to fetch reports", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadReports();
  }, []);

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-3xl font-bold gradient-text">Executive Reports</h1>
        <p className="text-clay-ink-muted mt-1">AI-generated summaries and insights</p>
      </div>

      {loading ? (
        <div className="text-center p-12 text-clay-ink-muted">Loading reports...</div>
      ) : reports.length === 0 ? (
        <div className="text-center p-12 clay-card text-clay-ink-muted">
          No reports generated yet. Complete a workflow to see results here.
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {reports.map((report) => (
            <div key={report.id} className="clay-card p-6 hover:translate-y-[-2px] transition-all duration-200">
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-center gap-3">
                  <div className="p-3 rounded-xl bg-clay-purple/15 text-clay-purple-dark">
                    <FileText className="w-6 h-6" />
                  </div>
                  <div>
                    <h3 className="text-xl font-bold text-clay-ink">{report.title || "Market Research Report"}</h3>
                    <p className="text-sm text-clay-ink-muted">{new Date(report.created_at).toLocaleDateString()}</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button 
                    onClick={async () => {
                      try {
                        const { downloadPdf } = await import('../api/client');
                        const blob = await downloadPdf(report.id);
                        const url = window.URL.createObjectURL(new Blob([blob]));
                        const link = document.createElement('a');
                        link.href = url;
                        link.setAttribute('download', `report_${report.id.substring(0,8)}.pdf`);
                        document.body.appendChild(link);
                        link.click();
                        link.parentNode?.removeChild(link);
                        window.URL.revokeObjectURL(url);
                      } catch (error) {
                        console.error('Download failed', error);
                        alert('Failed to download PDF. Please try again.');
                      }
                    }}
                    className="p-2 rounded-lg bg-clay-bg hover:bg-clay-blue/10 text-clay-ink-light transition-colors" title="Download PDF">
                    <Download className="w-4 h-4" />
                  </button>
                  <button
                    onClick={async () => {
                      if(confirm('Are you sure you want to delete this report?')) {
                        try {
                          await deleteReport(report.id);
                          loadReports();
                        } catch (e) {
                          console.error(e);
                        }
                      }
                    }}
                    className="p-2 rounded-lg bg-clay-coral/10 hover:bg-clay-coral/20 text-clay-coral transition-colors"
                    title="Delete Report"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
              
              <div className="mb-4">
                <h4 className="text-sm font-semibold text-clay-ink-muted mb-2 uppercase tracking-wider">Executive Summary</h4>
                <p className="text-clay-ink-light text-sm line-clamp-3">
                  {report.executive_summary}
                </p>
              </div>

              <div>
                <h4 className="text-sm font-semibold text-clay-ink-muted mb-2 uppercase tracking-wider">Recommendations</h4>
                <ul className="text-sm text-clay-ink-light list-disc list-inside space-y-1">
                  {(report.recommendations || []).slice(0, 3).map((rec: string, i: number) => (
                    <li key={i} className="truncate">{rec}</li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
