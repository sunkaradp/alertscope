{{- define "alertscope.labels" -}}
app.kubernetes.io/name: alertscope
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end }}

{{- define "alertscope.selector" -}}
app.kubernetes.io/name: alertscope
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
