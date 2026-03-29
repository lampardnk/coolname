package main

import (
	"fmt"

	appsv1 "github.com/pulumi/pulumi-kubernetes/sdk/v4/go/kubernetes/apps/v1"
	corev1 "github.com/pulumi/pulumi-kubernetes/sdk/v4/go/kubernetes/core/v1"
	metav1 "github.com/pulumi/pulumi-kubernetes/sdk/v4/go/kubernetes/meta/v1"
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
		nodeIP := additional["node_ip"]
		if nodeIP == "" {
			nodeIP = "localhost"
		}

		chal   := "pwn-heap"
		ns     := "ctf-challenges"
		labels := pulumi.StringMap{"app": pulumi.String(chal + "-" + id)}

		_, err := appsv1.NewDeployment(ctx, "deploy", &appsv1.DeploymentArgs{
			Metadata: &metav1.ObjectMetaArgs{Namespace: pulumi.String(ns)},
			Spec: &appsv1.DeploymentSpecArgs{
				Selector: &metav1.LabelSelectorArgs{MatchLabels: labels},
				Replicas: pulumi.Int(1),
				Template: &corev1.PodTemplateSpecArgs{
					Metadata: &metav1.ObjectMetaArgs{Labels: labels},
					Spec: &corev1.PodSpecArgs{
						TerminationGracePeriodSeconds: pulumi.Int(5),
					Containers: corev1.ContainerArray{&corev1.ContainerArgs{
							Name:  pulumi.String(chal),
							Image: pulumi.String("asia-southeast1-docker.pkg.dev/project-37bfe636-96dd-4d8c-b26/ctf-images/pwn-heap:latest"),
							Ports: corev1.ContainerPortArray{
								&corev1.ContainerPortArgs{ContainerPort: pulumi.Int(31337)},
							},
						Resources: &corev1.ResourceRequirementsArgs{
							Requests: pulumi.StringMap{
								"cpu":    pulumi.String("10m"),
								"memory": pulumi.String("32Mi"),
							},
							Limits: pulumi.StringMap{
								"cpu":    pulumi.String("500m"),
								"memory": pulumi.String("256Mi"),
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
				Type:     pulumi.String("NodePort"),
				Ports: corev1.ServicePortArray{
					&corev1.ServicePortArgs{
						Port:       pulumi.Int(31337),
						TargetPort: pulumi.Int(31337),
						Protocol:   pulumi.String("TCP"),
					},
				},
			},
		})
		if err != nil {
			return err
		}

		nodePort := svc.Spec.Ports().Index(pulumi.Int(0)).NodePort()
		connInfo := nodePort.ApplyT(func(port *int) string {
			if port == nil {
				return fmt.Sprintf("nc %s <port>", nodeIP)
			}
			return fmt.Sprintf("nc %s %d", nodeIP, *port)
		}).(pulumi.StringOutput)

		ctx.Export("connection_info", connInfo)
		return nil
	})
}
