{{/*
Expand the name of the chart.
*/}}
{{- define "dora.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "dora.namespace" -}}
{{- default .Release.Namespace .Values.namespace.name -}}
{{- end -}}

{{- define "dora.labels" -}}
app.kubernetes.io/name: {{ include "dora.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "dora.backend.image" -}}
{{ printf "%s:%s" .Values.image.backend.repository .Values.image.backend.tag }}
{{- end -}}

{{- define "dora.frontend.image" -}}
{{ printf "%s:%s" .Values.image.frontend.repository .Values.image.frontend.tag }}
{{- end -}}
