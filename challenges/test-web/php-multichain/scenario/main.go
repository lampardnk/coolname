package main

import (
	"fmt"

	appsv1 "github.com/pulumi/pulumi-kubernetes/sdk/v4/go/kubernetes/apps/v1"
	corev1 "github.com/pulumi/pulumi-kubernetes/sdk/v4/go/kubernetes/core/v1"
	metav1 "github.com/pulumi/pulumi-kubernetes/sdk/v4/go/kubernetes/meta/v1"
	netv1  "github.com/pulumi/pulumi-kubernetes/sdk/v4/go/kubernetes/networking/v1"
	"github.com/pulumi/pulumi/sdk/v3/go/pulumi"
	"github.com/pulumi/pulumi/sdk/v3/go/pulumi/config"
)

func main() {
	pulumi.Run(func(ctx *pulumi.Context) error {
		cfg := config.New(ctx, "")

		id := cfg.Get("identity")
		if id == "" {
			id = "preview"
		}

		additional := map[string]string{}
		_ = cfg.GetObject("additional", &additional)
		domain := additional["domain"]
		if domain == "" {
			domain = "placeholder.example.com"
		}

		chal   := "php-multichain"
		ns     := "ctf-challenges"
		host   := fmt.Sprintf("%s-%s.%s", id, chal, domain)
		labels := pulumi.StringMap{"app": pulumi.String(chal + "-" + id)}

		// PHP/Apache listens on port 80 — tests port-80 container routing
		containerPort := 80

		_, err := appsv1.NewDeployment(ctx, "deploy", &appsv1.DeploymentArgs{
			Metadata: &metav1.ObjectMetaArgs{Namespace: pulumi.String(ns)},
			Spec: &appsv1.DeploymentSpecArgs{
				Selector: &metav1.LabelSelectorArgs{MatchLabels: labels},
				Replicas: pulumi.Int(1),
				Template: &corev1.PodTemplateSpecArgs{
					Metadata: &metav1.ObjectMetaArgs{Labels: labels},
					Spec: &corev1.PodSpecArgs{
						Containers: corev1.ContainerArray{&corev1.ContainerArgs{
							Name:  pulumi.String(chal),
							Image: pulumi.String("asia-southeast1-docker.pkg.dev/project-37bfe636-96dd-4d8c-b26/ctf-images/php-multichain:latest"),
							Ports: corev1.ContainerPortArray{
								&corev1.ContainerPortArgs{ContainerPort: pulumi.Int(containerPort)},
							},
						Resources: &corev1.ResourceRequirementsArgs{
							Requests: pulumi.StringMap{
								"cpu":    pulumi.String("25m"),
								"memory": pulumi.String("64Mi"),
							},
							Limits: pulumi.StringMap{
								"cpu":    pulumi.String("500m"),
								"memory": pulumi.String("512Mi"),
							},
						},
						}},
					},
				},
			},
		})
		if err != nil {
			return err
		}

		svc, err := corev1.NewService(ctx, "svc", &corev1.ServiceArgs{
			Metadata: &metav1.ObjectMetaArgs{Namespace: pulumi.String(ns)},
			Spec: &corev1.ServiceSpecArgs{
				Selector: labels,
				Ports: corev1.ServicePortArray{
					&corev1.ServicePortArgs{
						Port:       pulumi.Int(80),
						TargetPort: pulumi.Int(containerPort),
					},
				},
			},
		})
		if err != nil {
			return err
		}

		_, err = netv1.NewIngress(ctx, "ingress", &netv1.IngressArgs{
			Metadata: &metav1.ObjectMetaArgs{
				Namespace: pulumi.String(ns),
				Annotations: pulumi.StringMap{
					"kubernetes.io/ingress.class": pulumi.String("traefik"),
				},
			},
			Spec: &netv1.IngressSpecArgs{
				Rules: netv1.IngressRuleArray{&netv1.IngressRuleArgs{
					Host: pulumi.String(host),
					Http: &netv1.HTTPIngressRuleValueArgs{
						Paths: netv1.HTTPIngressPathArray{&netv1.HTTPIngressPathArgs{
							Path:     pulumi.String("/"),
							PathType: pulumi.String("Prefix"),
							Backend: &netv1.IngressBackendArgs{
								Service: &netv1.IngressServiceBackendArgs{
									Name: svc.Metadata.Name().Elem(),
									Port: &netv1.ServiceBackendPortArgs{Number: pulumi.Int(80)},
								},
							},
						}},
					},
				}},
			},
		})
		if err != nil {
			return err
		}

		ctx.Export("connection_info", pulumi.String("http://"+host))
		return nil
	})
}
